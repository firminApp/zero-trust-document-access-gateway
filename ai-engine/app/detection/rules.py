"""Détection par règles : motifs + validateurs.

Cette famille couvre les formats fixes avec un rappel proche de 1. Elle ne
remplace pas la NER (aucune regex ne trouve un patronyme) : les deux familles
sont complémentaires et fusionnées par `merge.py`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.detection import validators
from app.models import Entite, MethodeDetect

# --- Motifs ------------------------------------------------------------------

MOTIF_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}",
)

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


@dataclass
class Regle:
    """Un motif, le type d'entité qu'il produit, et son validateur éventuel."""

    type_entite: str
    motif: re.Pattern[str]
    validateur: Callable[[str], bool] | None = None
    # Lorsque le validateur échoue : on abandonne la détection (True) ou on la
    # conserve en non validée avec un score dégradé (False).
    rejeter_si_invalide: bool = True
    score_valide: float = 0.99
    score_non_valide: float = 0.55
    groupe: int = 0


REGLES: tuple[Regle, ...] = (
    Regle("EMAIL", MOTIF_EMAIL, None, score_valide=0.97),
    Regle("IBAN", MOTIF_IBAN, validators.iban_valide, rejeter_si_invalide=True),
    Regle("CARTE_BANCAIRE", MOTIF_CARTE, validators.luhn_valide, rejeter_si_invalide=True),
    Regle("TELEPHONE", MOTIF_TELEPHONE, validators.telephone_valide, rejeter_si_invalide=False),
    Regle("DATE_NAISSANCE", MOTIF_DATE_NUM, validators.date_naissance_valide, rejeter_si_invalide=True),
    Regle("DATE_NAISSANCE", MOTIF_DATE_TEXTE, validators.date_naissance_valide, rejeter_si_invalide=True),
    Regle("PLAQUE_IMMAT", MOTIF_PLAQUE, None, score_valide=0.70),
    Regle("NUM_CLIENT", MOTIF_NUM_CLIENT, None, score_valide=0.90, groupe=1),
)


def detecter(texte: str) -> list[Entite]:
    """Applique toutes les règles au texte normalisé."""
    entites: list[Entite] = []
    minuscule = texte.lower()

    for regle in REGLES:
        entites.extend(_appliquer(regle, texte))

    entites.extend(_detecter_pieces(texte, minuscule))
    return entites


def _appliquer(regle: Regle, texte: str) -> Iterable[Entite]:
    for correspondance in regle.motif.finditer(texte):
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
                if regle.rejeter_si_invalide:
                    continue
                score = regle.score_non_valide

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

        entites.append(
            Entite(
                typeEntite="NUM_PIECE_IDENTITE",
                valeur=valeur,
                debut=correspondance.start(),
                fin=correspondance.start() + len(valeur),
                score=0.95 if valide else 0.75,
                methode=MethodeDetect.regle,
                valide=valide,
            )
        )
    return entites
