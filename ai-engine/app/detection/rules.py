"""Détection par règles : motifs + validateurs.

Cette famille couvre les formats fixes avec un rappel proche de 1. Elle ne
remplace pas la NER (aucune regex ne trouve un patronyme) : les deux familles
sont complémentaires et fusionnées par `merge.py`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.detection import reparation_ocr, validators
from app.models import Entite, MethodeDetect

# --- Motifs ------------------------------------------------------------------

MOTIF_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}",
)

# Variante pour texte océrisé.
#
# Deux relaxations, dictées par ce que l'OCR fait réellement aux adresses,
# mesuré sur le corpus dégradé :
#
#   * l'extension est rognée ou bruitée — `poste.ci` ressort en `poste.c`,
#     `mail.bj` en `mail.b]` — d'où `{1,63}` au lieu de `{2,63}` ;
#   * un caractère quelconque s'insère dans le domaine — `poste` ressort en
#     `pos'e`, `boateng` en `boa'eng`. Plutôt que d'énumérer indéfiniment les
#     caractères parasites rencontrés, on admet tout caractère non blanc.
#
# La sélectivité reste portée par la structure, qui est forte : un `@` sans
# espace, suivi d'un domaine, d'un point et d'une extension alphabétique. Dans
# un document, une telle chaîne est une adresse électronique. Le prix est une
# précision moindre sur les scans, ce que le F2 accepte par construction.
MOTIF_EMAIL_OCR = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{1,63}")

# Indicatifs de la zone CEDEAO visés par le projet + France, ou format local.
# Les gardes de bord excluent les chiffres adjacents (un numéro tronqué au
# milieu d'un plus long) sans rejeter un point de fin de phrase.
MOTIF_TELEPHONE = re.compile(
    r"(?<!\w)(?<!\d[.,])(?:"
    r"(?:\+|00)\s?(?:221|229|228|225|233|226|223|227|234|33)"
    r"(?:[\s.\-]?\d){8,10}"
    r"|"
    r"(?:0?\d{2})(?:[\s.\-]\d{2}){3,4}"
    r")(?!\w)(?![.,]\d)"
)

# Séparateur limité à l'espace et au tiret : autoriser `\s` laisserait le motif
# franchir un saut de ligne et absorber le début de l'enregistrement suivant.
MOTIF_IBAN = re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?:[ \-]?[A-Z0-9]){11,30}(?![A-Z0-9])")

# Variante pour texte océrisé. Les deux chiffres de contrôle sont la position la
# plus fragile de l'IBAN : mesuré sur le corpus, `SN68…` ressort en `SNG8…`,
# `SNS8…`, `SN93…` en `SNS3…`. Le motif strict exige `\d{2}` et ne correspond
# alors plus DU TOUT — il n'y a même pas de candidat à soumettre au mod-97, et
# aucune tolérance sur le validateur ne peut rattraper cela. La confusion se
# joue donc au niveau du motif.
CONFUSIONS_CHIFFRES = "OISGBZQD"   # 0/O, 1/I, 5/S, 6/G, 8/B, 2/Z, 9/Q, 0/D
MOTIF_IBAN_OCR = re.compile(
    r"(?<![A-Z0-9])[A-Z]{2}[0-9" + CONFUSIONS_CHIFFRES + r"]{2}"
    r"(?:[ \-]?[A-Z0-9]){11,30}(?![A-Z0-9])"
)

MOTIF_CARTE = re.compile(r"(?<![\d.])(?:\d[ .\-]?){12,18}\d(?![\d.])")

MOTIF_DATE_NUM = re.compile(
    r"(?<![\d/])\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}(?![\d/])"
)
MOTIF_DATE_TEXTE = re.compile(
    r"(?<!\w)\d{1,2}(?:er)?\s+"
    r"(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|"
    r"octobre|novembre|d[ée]cembre)\s+\d{4}(?!\w)",
    flags=re.IGNORECASE,
)

MOTIF_PIECE = re.compile(r"(?<![\w])(?:[A-Z]{0,2}\d[\d .\-]{5,17}\d)(?![\w])")

# Formats d'immatriculation : SN « AA-1234-XY », BJ/TG « AB 1234 RB », FR « AA-123-AA ».
MOTIF_PLAQUE = re.compile(
    r"(?<![\w-])(?:"
    r"[A-Z]{2}[\s-]?\d{3,4}[\s-]?[A-Z]{1,3}"
    r"|\d{4}[\s-]?[A-Z]{2}[\s-]?\d{2}"
    r")(?![\w-])"
)

MOTIF_NUM_CLIENT = re.compile(
    r"(?:n[°o]\s*client|num[ée]ro\s+client|r[ée]f[ée]rence\s+client|id\s+client"
    r"|dossier\s+n[°o]|r[ée]f[ée]rence\s+dossier|n[°o]\s*de\s+dossier)"
    r"\s*[:.\-]?\s*([A-Z0-9\-]{4,20})",
    flags=re.IGNORECASE,
)

# Indices lexicaux qui font basculer un nombre ambigu vers « pièce d'identité ».
INDICES_PIECE = (
    "cni", "carte nationale", "carte d'identite", "carte d'identité",
    "piece d'identite", "pièce d'identité", "nin", "npi", "nif",
    "passeport", "permis", "numero d'identification", "numéro d'identification",
    "identifiant national", "titre de sejour", "titre de séjour",
)

FENETRE_INDICE = 60

# Scores de `NUM_PIECE_IDENTITE`, du plus fort au plus faible.
#
# Le cas qui commande ces valeurs : un numéro national de 13 chiffres satisfait
# parfois le contrôle de Luhn par pure coïncidence, et `CARTE_BANCAIRE` — validé,
# score 0,99 — l'emporte alors à la fusion. Les deux types étant `critique`, la
# donnée reste protégée à l'identique et aucune fuite n'en résulte ; mais le
# document est décrit à tort comme portant un numéro de carte.
#
# Quand le document **étiquette** lui-même le numéro (« N° CNI : »), ce contexte
# est une preuve plus forte qu'une coïncidence de format : le score dépasse alors
# celui d'un Luhn validé. Sans étiquette, l'ambiguïté est réelle et on ne la
# tranche pas artificiellement.
SCORE_PIECE_CONTEXTE_ET_FORMAT = 0.995
SCORE_PIECE_FORMAT_SEUL = 0.95
SCORE_PIECE_CONTEXTE_SEUL = 0.75


@dataclass
class Regle:
    """Un motif, le type d'entité qu'il produit, et son validateur éventuel."""

    type_entite: str
    motif: re.Pattern[str]
    validateur: Callable[[str], bool] | None = None
    # Motif de substitution pour du texte océrisé, quand les confusions de
    # caractères empêchent le motif strict de correspondre.
    motif_ocr: re.Pattern[str] | None = None
    # Lorsque le validateur échoue : on abandonne la détection (True) ou on la
    # conserve en non validée avec un score dégradé (False).
    rejeter_si_invalide: bool = True
    # Vrai lorsque le validateur est une **somme de contrôle** (mod-97, Luhn) et
    # non un simple contrôle de plausibilité. La distinction commande le
    # comportement sur du texte océrisé : une somme de contrôle est détruite par
    # une seule confusion de caractère, alors que le motif, lui, reconnaît
    # toujours la donnée. Rejeter dans ce cas fait disparaître un vrai IBAN.
    # Un contrôle de plausibilité (une date au 32 du mois) reste, au contraire,
    # une bonne raison d'écarter le candidat.
    somme_de_controle: bool = False
    score_valide: float = 0.99
    score_non_valide: float = 0.55
    # Score attribué à un candidat dont la somme de contrôle échoue sur un texte
    # issu de l'OCR.
    #
    # Élevé, et ce n'est pas une commodité. Une chaîne de 28 caractères au
    # format IBAN dans un document océrisé est bien plus probablement un IBAN
    # qu'une étiquette NER générique : l'échec du mod-97 est *expliqué* par le
    # bruit de lecture, il n'est pas un indice contre la nature de la donnée.
    #
    # Une valeur basse a été essayée (0,45) et mesurée nuisible : la fusion,
    # qui départage à empan égal par le score, faisait gagner le
    # `LOCALITE`/`ORGANISATION` rendu par spaCy — dont le score de 0,85 est une
    # constante arbitraire et non une probabilité. L'IBAN n'était pas seulement
    # manqué, il était **remplacé**, donc reclassé de `critique` à `faible` :
    # un sous-classement, la faille même que M5 interdit.
    score_ocr_non_valide: float = 0.90
    groupe: int = 0


REGLES: tuple[Regle, ...] = (
    Regle("EMAIL", MOTIF_EMAIL, None, motif_ocr=MOTIF_EMAIL_OCR, score_valide=0.97),
    Regle(
        "IBAN",
        MOTIF_IBAN,
        validators.iban_valide,
        motif_ocr=MOTIF_IBAN_OCR,
        rejeter_si_invalide=True,
        somme_de_controle=True,
    ),
    Regle(
        "CARTE_BANCAIRE",
        MOTIF_CARTE,
        validators.luhn_valide,
        rejeter_si_invalide=True,
        somme_de_controle=True,
    ),
    Regle("TELEPHONE", MOTIF_TELEPHONE, validators.telephone_valide, rejeter_si_invalide=False),
    Regle("DATE_NAISSANCE", MOTIF_DATE_NUM, validators.date_naissance_valide, rejeter_si_invalide=True),
    Regle("DATE_NAISSANCE", MOTIF_DATE_TEXTE, validators.date_naissance_valide, rejeter_si_invalide=True),
    Regle("PLAQUE_IMMAT", MOTIF_PLAQUE, None, score_valide=0.70),
    Regle("NUM_CLIENT", MOTIF_NUM_CLIENT, None, score_valide=0.90, groupe=1),
)


def detecter(texte: str, ocr: bool = False) -> list[Entite]:
    """Applique toutes les règles au texte normalisé.

    `ocr=True` signale que le texte vient d'une reconnaissance optique, et
    active deux tolérances mesurées comme nécessaires par la campagne de bout
    en bout (`evaluation/run_e2e_eval.py`) :

      1. les candidats dont une **somme de contrôle** échoue sont conservés, à
         score réduit, au lieu d'être écartés ;
      2. les règles sont rejouées sur une variante du texte où les espaces
         parasites internes aux jetons ont été retirés.

    Aucune des deux ne s'applique au texte propre : la précision y reste
    intacte. C'est un arbitrage assumé et local — sur un scan, on préfère
    masquer un faux IBAN que laisser passer un vrai, ce que le F2 accepte par
    construction.
    """
    entites = _detecter_sur(texte, ocr)

    if ocr and reparation_ocr.vaut_la_peine(texte):
        repare = reparation_ocr.reparer(texte)
        for entite in _detecter_sur(repare.texte, ocr):
            debut, fin = repare.span_source(entite.debut, entite.fin)
            # La valeur est relue dans le texte d'origine : c'est elle que la
            # protection devra effacer, espaces parasites compris.
            entites.append(
                entite.model_copy(
                    update={"debut": debut, "fin": fin, "valeur": texte[debut:fin]}
                )
            )

    return entites


def _detecter_sur(texte: str, ocr: bool) -> list[Entite]:
    entites: list[Entite] = []
    minuscule = texte.lower()

    for regle in REGLES:
        entites.extend(_appliquer(regle, texte, ocr))

    entites.extend(_detecter_pieces(texte, minuscule))
    return entites


def _appliquer(regle: Regle, texte: str, ocr: bool = False) -> Iterable[Entite]:
    motif = regle.motif_ocr if (ocr and regle.motif_ocr is not None) else regle.motif

    for correspondance in motif.finditer(texte):
        valeur = correspondance.group(regle.groupe)
        if not valeur or not valeur.strip():
            continue
        debut = correspondance.start(regle.groupe)
        fin = correspondance.end(regle.groupe)

        # Recadrage sur la valeur utile lorsque le motif capture des espaces.
        rogne_gauche = len(valeur) - len(valeur.lstrip())
        rogne_droite = len(valeur) - len(valeur.rstrip())
        valeur = valeur.strip()
        debut += rogne_gauche
        fin -= rogne_droite

        valide = True
        score = regle.score_valide
        if regle.validateur is not None:
            valide = regle.validateur(valeur)
            if not valide:
                # Sur du texte océrisé, une somme de contrôle qui échoue signale
                # plus souvent un caractère mal lu qu'une fausse détection : on
                # conserve le candidat plutôt que de perdre la donnée.
                tolere = ocr and regle.somme_de_controle
                if regle.rejeter_si_invalide and not tolere:
                    continue
                score = regle.score_ocr_non_valide if tolere else regle.score_non_valide

        yield Entite(
            typeEntite=regle.type_entite,
            valeur=valeur,
            debut=debut,
            fin=fin,
            score=score,
            methode=MethodeDetect.regle,
            valide=valide and regle.validateur is not None,
        )


def _detecter_pieces(texte: str, minuscule: str) -> list[Entite]:
    """Numéros de pièce d'identité : motif large, resserré par le contexte.

    Le motif seul attraperait toute suite de chiffres. On exige donc soit un
    format national reconnu par le validateur, soit un indice lexical proche
    (« CNI », « NIN », « passeport »…) dans une fenêtre de 60 caractères.

    Les deux réunis valent plus que chacun séparément : voir
    `SCORE_PIECE_CONTEXTE_ET_FORMAT`.
    """
    entites: list[Entite] = []
    for correspondance in MOTIF_PIECE.finditer(texte):
        valeur = correspondance.group(0).strip()
        compact = re.sub(r"[\s.\-]", "", valeur)
        if not compact or len(compact) < 8:
            continue

        valide = validators.piece_identite_valide(valeur)
        debut_fenetre = max(0, correspondance.start() - FENETRE_INDICE)
        contexte = minuscule[debut_fenetre : correspondance.start()]
        indice = any(mot in contexte for mot in INDICES_PIECE)

        if not valide and not indice:
            continue

        if valide and indice:
            score = SCORE_PIECE_CONTEXTE_ET_FORMAT
        elif valide:
            score = SCORE_PIECE_FORMAT_SEUL
        else:
            score = SCORE_PIECE_CONTEXTE_SEUL

        entites.append(
            Entite(
                typeEntite="NUM_PIECE_IDENTITE",
                valeur=valeur,
                debut=correspondance.start(),
                fin=correspondance.start() + len(valeur),
                score=score,
                methode=MethodeDetect.regle,
                valide=valide,
            )
        )
    return entites
