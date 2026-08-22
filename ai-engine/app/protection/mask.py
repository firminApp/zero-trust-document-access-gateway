"""Application de la protection au document, format par format (M6).

Le masquage n'est pas une opération sur du texte : c'est une opération sur un
**document**, et chaque format a sa propre notion de « supprimer une donnée ».

Piège central, sur lequel ce module est explicite : sur un PDF, dessiner un
rectangle noir ne supprime rien. Le texte reste sous le rectangle et ressort au
copier-coller. Seul `apply_redactions()` retire réellement le contenu.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Callable

import cv2
import fitz
import numpy as np

from app.extraction import router
from app.extraction.resultat import ResultatExtraction
from app.models import Entite

logger = logging.getLogger(__name__)

PUCE = "•"


# --- Fabrication de la valeur de remplacement --------------------------------


def masquer_valeur(valeur: str, type_entite: str | None = None) -> str:
    """Produit la forme masquée d'une valeur.

    On conserve le premier caractère de chaque mot et les séparateurs : le
    support garde de quoi vérifier qu'il parle du bon dossier (« J••• D••••• »
    reste reconnaissable pour l'agent qui a la personne au téléphone) sans que
    la donnée soit lisible.
    """
    if not valeur:
        return valeur

    if (type_entite or "").upper() == "EMAIL" and "@" in valeur:
        local, _, domaine = valeur.partition("@")
        premier = local[0] if local else ""
        return f"{premier}{PUCE * 6}@{PUCE * 4}" if domaine else f"{premier}{PUCE * 6}"

    morceaux = re.split(r"([^0-9A-Za-zÀ-ÖØ-öø-ÿ]+)", valeur)
    resultat: list[str] = []
    for morceau in morceaux:
        if not morceau or not re.match(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]", morceau):
            resultat.append(morceau)
            continue
        if len(morceau) == 1:
            resultat.append(PUCE)
        else:
            resultat.append(morceau[0] + PUCE * (len(morceau) - 1))
    return "".join(resultat)


# --- Aiguillage par format ---------------------------------------------------


def appliquer(
    contenu: bytes,
    type_mime: str | None,
    nom: str | None,
    extraction: ResultatExtraction,
    entites: list[Entite],
    remplacer: Callable[[Entite], str],
) -> tuple[bytes, int, str]:
    """Applique `remplacer` à chaque entité. Retourne (octets, nb, type MIME)."""
    if not entites:
        return contenu, 0, router.deviner_type(contenu, type_mime, nom)

    effectif = router.deviner_type(contenu, type_mime, nom)

    if effectif == router.MIME_PDF:
        return _appliquer_pdf(contenu, extraction, entites, remplacer)
    if effectif == router.MIME_DOCX:
        return _appliquer_docx(contenu, entites, remplacer)
    if effectif in router.MIMES_IMAGE:
        return _appliquer_image(contenu, extraction, entites, effectif)
    return _appliquer_texte(contenu, extraction, entites, remplacer)


# --- Texte et CSV ------------------------------------------------------------


def _appliquer_texte(
    contenu: bytes,
    extraction: ResultatExtraction,
    entites: list[Entite],
    remplacer: Callable[[Entite], str],
) -> tuple[bytes, int, str]:
    """Substitution par offsets, en partant de la fin.

    Remonter le document évite d'avoir à recalculer les positions suivantes
    après chaque substitution de longueur différente.
    """
    source = extraction.brut
    ordonnees = sorted(entites, key=lambda e: e.debut, reverse=True)

    nombre = 0
    fin_precedente = len(source) + 1
    for entite in ordonnees:
        debut_src, fin_src = extraction.normalise.span_source(entite.debut, entite.fin)
        if debut_src >= fin_src or fin_src > len(source):
            continue
        if fin_src > fin_precedente:
            continue  # chevauchement résiduel : déjà traité par l'entité suivante
        source = source[:debut_src] + remplacer(entite) + source[fin_src:]
        fin_precedente = debut_src
        nombre += 1

    return source.encode("utf-8"), nombre, "text/plain"


# --- PDF ---------------------------------------------------------------------


def _appliquer_pdf(
    contenu: bytes,
    extraction: ResultatExtraction,
    entites: list[Entite],
    remplacer: Callable[[Entite], str],
) -> tuple[bytes, int, str]:
    nombre = 0
    with fitz.open(stream=contenu, filetype="pdf") as document:
        non_trouvees: list[Entite] = []

        for entite in entites:
            valeur = entite.valeur.strip()
            if not valeur:
                continue
            remplacement = remplacer(entite)
            pages_cibles = _pages_candidates(document, entite, extraction)

            trouvee = False
            for page in pages_cibles:
                rectangles = page.search_for(valeur, quads=False)
                for rectangle in rectangles:
                    page.add_redact_annot(
                        rectangle,
                        text=remplacement,
                        fontsize=max(6, rectangle.height * 0.7),
                        fill=(1, 1, 1),
                        text_color=(0, 0, 0),
                    )
                    trouvee = True
            if trouvee:
                nombre += 1
            else:
                non_trouvees.append(entite)

        for page in document:
            # C'est cette ligne qui supprime réellement le texte. Sans elle, le
            # rectangle n'est qu'un calque et la donnée reste extractible.
            page.apply_redactions()

        if non_trouvees:
            nombre += _caviarder_par_boites(document, extraction, non_trouvees)

        sortie = document.tobytes(garbage=4, deflate=True)

    return sortie, nombre, router.MIME_PDF


def _pages_candidates(
    document: fitz.Document, entite: Entite, extraction: ResultatExtraction
) -> list[fitz.Page]:
    """Restreint la recherche à la page probable, avec repli sur tout le document."""
    numero = entite.page or extraction.page_de(entite.debut)
    if numero and 1 <= numero <= document.page_count:
        return [document[numero - 1]]
    return list(document)


def _caviarder_par_boites(
    document: fitz.Document, extraction: ResultatExtraction, entites: list[Entite]
) -> int:
    """Repli pour les PDF scannés : rectangles opaques aux boîtes OCR.

    La couche texte est absente, `search_for` ne trouve rien. On s'appuie donc
    sur les boîtes produites par l'OCR, ramenées à l'échelle de la page.
    """
    if not extraction.boites:
        logger.warning(
            "%d entité(s) non localisée(s) dans le PDF et aucune boîte OCR "
            "disponible : elles ne peuvent pas être caviardées",
            len(entites),
        )
        return 0

    from app.config import get_settings

    facteur = 72.0 / max(1, get_settings().ocr_dpi)
    nombre = 0

    for entite in entites:
        boites = [
            b
            for b in extraction.boites
            if b.debut < entite.fin and entite.debut < b.fin
        ]
        if not boites:
            continue
        for boite in boites:
            index = max(0, min(document.page_count - 1, boite.page - 1))
            page = document[index]
            rectangle = fitz.Rect(
                boite.x * facteur,
                boite.y * facteur,
                (boite.x + boite.largeur) * facteur,
                (boite.y + boite.hauteur) * facteur,
            )
            page.draw_rect(rectangle, color=(0, 0, 0), fill=(0, 0, 0), overlay=True)
        nombre += 1

    return nombre


# --- DOCX --------------------------------------------------------------------


def _appliquer_docx(
    contenu: bytes, entites: list[Entite], remplacer: Callable[[Entite], str]
) -> tuple[bytes, int, str]:
    """Substitution au niveau du run.

    Word découpe un paragraphe en runs selon le formatage : « Jean Dupont »
    peut occuper trois runs. On réécrit donc le paragraphe entier dans son
    premier run et on vide les suivants dès qu'une substitution le traverse.
    """
    from docx import Document

    document = Document(io.BytesIO(contenu))
    substitutions = {
        e.valeur.strip(): remplacer(e) for e in entites if e.valeur.strip()
    }
    compteur = {"n": 0}

    def traiter_paragraphe(paragraphe) -> None:  # noqa: ANN001
        texte = paragraphe.text
        if not texte:
            return
        nouveau = texte
        touche = False
        for valeur, remplacement in substitutions.items():
            if valeur in nouveau:
                nouveau = nouveau.replace(valeur, remplacement)
                compteur["n"] += 1
                touche = True
        if not touche:
            return
        runs = paragraphe.runs
        if not runs:
            return
        runs[0].text = nouveau
        for run in runs[1:]:
            run.text = ""

    def traiter_conteneur(conteneur) -> None:  # noqa: ANN001
        for paragraphe in getattr(conteneur, "paragraphs", []):
            traiter_paragraphe(paragraphe)
        for tableau in getattr(conteneur, "tables", []):
            for rangee in tableau.rows:
                for cellule in rangee.cells:
                    traiter_conteneur(cellule)

    traiter_conteneur(document)
    for section in document.sections:
        traiter_conteneur(section.header)
        traiter_conteneur(section.footer)

    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue(), compteur["n"], router.MIME_DOCX


# --- Image -------------------------------------------------------------------


def _appliquer_image(
    contenu: bytes,
    extraction: ResultatExtraction,
    entites: list[Entite],
    type_mime: str,
) -> tuple[bytes, int, str]:
    """Rectangle opaque aux boîtes englobantes OCR.

    Sur une image il n'y a pas de couche texte à retirer : l'aplat *est* la
    suppression, à condition de réencoder l'image (ce que fait `imencode`).
    """
    tampon = np.frombuffer(contenu, dtype=np.uint8)
    image = cv2.imdecode(tampon, cv2.IMREAD_COLOR)
    if image is None:
        logger.error("Image illisible, protection impossible")
        return contenu, 0, type_mime

    nombre = 0
    for entite in entites:
        boites = [
            b for b in extraction.boites if b.debut < entite.fin and entite.debut < b.fin
        ]
        if not boites:
            continue
        for boite in boites:
            cv2.rectangle(
                image,
                (boite.x, boite.y),
                (boite.x + boite.largeur, boite.y + boite.hauteur),
                (0, 0, 0),
                thickness=-1,
            )
        nombre += 1

    extension = ".png" if type_mime == "image/png" else ".jpg"
    succes, encodee = cv2.imencode(extension, image)
    if not succes:
        return contenu, 0, type_mime
    return encodee.tobytes(), nombre, type_mime
