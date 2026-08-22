"""OCR Tesseract avec prétraitement OpenCV.

Le prétraitement pèse davantage sur le taux d'erreur que le choix du moteur :
sur les scans dégradés du corpus, la chaîne ci-dessous divise le CER par un
facteur significatif par rapport à une soumission de l'image brute. Il ne faut
donc pas le contourner, même quand l'image « a l'air propre ».

Ordre imposé : niveaux de gris -> binarisation Otsu adaptative (fenêtre 31)
-> redressement par angle dominant (Hough) -> filtre médian.
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache

import cv2
import numpy as np
import pytesseract
from PIL import Image

from app.config import get_settings
from app.extraction.resultat import BoiteMot, ResultatExtraction, depuis_texte
from app.models import MethodeExtraction

logger = logging.getLogger(__name__)

FENETRE_BINARISATION = 31

# Redressement : conditions de confiance.
#
# Sur une image bruitée, Hough détecte 70 à 110 « lignes » qui ne sont que du
# grain, et leur angle médian est arbitraire. Faire pivoter la page de ce petit
# angle arbitraire, en interpolation cubique, étale le grain en amas que
# Tesseract lit comme du texte : mesuré à 1135 caractères restitués pour 174
# attendus, soit un CER de 5,9. Un redressement qui se trompe est bien plus
# coûteux qu'un redressement omis.
#
# Ce qui distingue une vraie inclinaison du bruit, ce n'est pas le nombre de
# lignes mais leur ACCORD. Mesuré sur le corpus dégradé :
#   inclinaison réelle de 3°  -> écart absolu médian 0,06 à 0,13°
#   bruit gaussien (sigma=18) -> écart absolu médian 1,10 à 1,84°
# Le seuil ci-dessous est placé dans cet intervalle, largement à distance des
# deux régimes.
DISPERSION_MAX_DEGRES = 0.5
MIN_LIGNES_REDRESSEMENT = 8
ANGLE_MIN_DEGRES = 0.15


def version_tesseract() -> str:
    try:
        return str(pytesseract.get_tesseract_version())
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        logger.warning("Tesseract indisponible : %s", exc)
        return "indisponible"


@lru_cache(maxsize=4)
def langue_effective(demandee: str) -> str:
    """Retourne `demandee` si le pack est installé, sinon un repli explicite.

    L'image Docker installe `tesseract-ocr-fra`. Hors conteneur le pack peut
    manquer : on préfère un OCR dégradé et bruyamment signalé à un service qui
    répond 500 sur tous les scans.
    """
    try:
        disponibles = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        logger.warning("Liste des langues Tesseract illisible : %s", exc)
        return demandee

    if demandee in disponibles:
        return demandee
    repli = "eng" if "eng" in disponibles else next(iter(sorted(disponibles)), demandee)
    logger.warning(
        "Pack Tesseract '%s' absent (disponibles : %s) — repli sur '%s'. "
        "Le CER sera dégradé sur les documents en français.",
        demandee,
        ", ".join(sorted(disponibles)) or "aucun",
        repli,
    )
    return repli


def pretraiter(image: np.ndarray) -> np.ndarray:
    """Applique la chaîne de prétraitement complète à une image BGR ou grise."""
    gris = _en_niveaux_de_gris(image)
    binaire = _binariser(gris)
    redresse = _redresser(binaire)
    return cv2.medianBlur(redresse, 3)


def _en_niveaux_de_gris(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _binariser(gris: np.ndarray) -> np.ndarray:
    """Binarisation adaptative de type Otsu sur une fenêtre de 31 pixels.

    L'adaptatif gaussien local suit les variations d'éclairage d'une photo de
    document, là où un Otsu global perd les zones sombres.
    """
    return cv2.adaptiveThreshold(
        gris,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        FENETRE_BINARISATION,
        10,
    )


def _redresser(binaire: np.ndarray) -> np.ndarray:
    """Corrige l'inclinaison par l'angle dominant des lignes de Hough."""
    inverse = cv2.bitwise_not(binaire)
    contours = cv2.Canny(inverse, 50, 150, apertureSize=3)
    lignes = cv2.HoughLinesP(
        contours, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10
    )
    if lignes is None:
        return binaire

    angles: list[float] = []
    # Selon la version d'OpenCV, HoughLinesP rend (N,1,4) ou (N,4).
    for ligne in np.asarray(lignes).reshape(-1, 4):
        x1, y1, x2, y2 = ligne
        if x2 == x1:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # On ne retient que les lignes proches de l'horizontale : les bords
        # verticaux d'un tableau fausseraient l'angle dominant.
        if -20 < angle < 20:
            angles.append(float(angle))

    if len(angles) < MIN_LIGNES_REDRESSEMENT:
        return binaire

    tableau = np.asarray(angles)
    angle_dominant = float(np.median(tableau))
    dispersion = float(np.median(np.abs(tableau - angle_dominant)))

    if dispersion > DISPERSION_MAX_DEGRES:
        # Les lignes ne s'accordent pas : la mesure ne veut rien dire. On
        # préfère une page non redressée à une page abîmée.
        logger.debug(
            "Redressement écarté : %d lignes, dispersion %.2f° (> %.2f°)",
            len(angles),
            dispersion,
            DISPERSION_MAX_DEGRES,
        )
        return binaire

    if abs(angle_dominant) < ANGLE_MIN_DEGRES:
        return binaire

    hauteur, largeur = binaire.shape[:2]
    centre = (largeur // 2, hauteur // 2)
    matrice = cv2.getRotationMatrix2D(centre, angle_dominant, 1.0)
    return cv2.warpAffine(
        binaire,
        matrice,
        (largeur, hauteur),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _tableau_depuis_octets(contenu: bytes) -> np.ndarray:
    tampon = np.frombuffer(contenu, dtype=np.uint8)
    image = cv2.imdecode(tampon, cv2.IMREAD_COLOR)
    if image is None:
        # Repli Pillow : certains PNG/TIFF ne passent pas par imdecode.
        with Image.open(io.BytesIO(contenu)) as pil:
            image = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    return image


def ocr_image_array(image: np.ndarray, page: int = 1) -> tuple[str, list[BoiteMot], float]:
    """OCR d'une image déjà chargée. Retourne (texte, boîtes, confiance moyenne)."""
    parametres = get_settings()
    preparee = pretraiter(image)
    donnees = pytesseract.image_to_data(
        preparee,
        lang=langue_effective(parametres.ocr_lang),
        output_type=pytesseract.Output.DICT,
        config="--oem 3 --psm 6",
    )

    morceaux: list[str] = []
    boites: list[BoiteMot] = []
    confiances: list[float] = []
    ligne_courante: int | None = None
    curseur = 0

    for index, mot in enumerate(donnees["text"]):
        if not mot or not mot.strip():
            continue
        cle_ligne = (
            donnees["block_num"][index],
            donnees["par_num"][index],
            donnees["line_num"][index],
        )
        if ligne_courante is not None and cle_ligne != ligne_courante:
            morceaux.append("\n")
            curseur += 1
        elif ligne_courante is not None:
            morceaux.append(" ")
            curseur += 1
        ligne_courante = cle_ligne  # type: ignore[assignment]

        try:
            confiance = float(donnees["conf"][index])
        except (TypeError, ValueError):
            confiance = -1.0
        if confiance >= 0:
            confiances.append(confiance)

        boites.append(
            BoiteMot(
                debut=curseur,
                fin=curseur + len(mot),
                x=int(donnees["left"][index]),
                y=int(donnees["top"][index]),
                largeur=int(donnees["width"][index]),
                hauteur=int(donnees["height"][index]),
                page=page,
                confiance=confiance,
            )
        )
        morceaux.append(mot)
        curseur += len(mot)

    texte = "".join(morceaux)
    confiance_moyenne = float(np.mean(confiances)) if confiances else 0.0
    return texte, boites, confiance_moyenne


def extraire(contenu: bytes) -> ResultatExtraction:
    """Extrait le texte d'une image (JPEG, PNG, TIFF…) par OCR."""
    image = _tableau_depuis_octets(contenu)
    texte, boites, confiance = ocr_image_array(image, page=1)

    resultat = depuis_texte(
        texte,
        MethodeExtraction.ocr,
        pages_brutes=[texte],
        cer_estime=cer_estime_depuis_confiance(confiance),
    )
    resultat.boites = reprojeter_boites(boites, resultat)
    return resultat


def cer_estime_depuis_confiance(confiance_moyenne: float) -> float | None:
    """Estimation grossière du CER à partir de la confiance Tesseract.

    Ce n'est pas une mesure : le CER réel se calcule contre une vérité terrain
    dans `evaluation/run_ocr_eval.py`. La valeur sert uniquement d'indicateur
    de qualité renvoyé à la passerelle.
    """
    if confiance_moyenne <= 0:
        return None
    return round(max(0.0, min(1.0, 1.0 - confiance_moyenne / 100.0)), 4)


def reprojeter_boites(
    boites: list[BoiteMot], resultat: ResultatExtraction
) -> list[BoiteMot]:
    """Traduit les offsets des boîtes du texte brut vers le texte normalisé."""
    table = resultat.normalise.map_offsets
    # Table inverse : offset source -> première position normalisée.
    inverse: dict[int, int] = {}
    for position_norm, offset_src in enumerate(table):
        inverse.setdefault(offset_src, position_norm)

    def traduire(offset_src: int) -> int:
        if offset_src in inverse:
            return inverse[offset_src]
        candidats = [o for o in inverse if o >= offset_src]
        return inverse[min(candidats)] if candidats else len(resultat.texte)

    return [
        BoiteMot(
            debut=traduire(boite.debut),
            fin=traduire(boite.fin),
            x=boite.x,
            y=boite.y,
            largeur=boite.largeur,
            hauteur=boite.hauteur,
            page=boite.page,
            confiance=boite.confiance,
        )
        for boite in boites
    ]
