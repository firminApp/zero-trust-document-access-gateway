"""Validateurs structurels des détections par règle.

Un motif seul a une spécificité faible : « 16 chiffres » attrape un numéro de
commande aussi bien qu'une carte bancaire. Adjoindre un validateur transforme
un motif bruyant en détecteur très précis, sans rien coûter au rappel — c'est
ce qui rend la combinaison règles + NER supérieure à chacune prise seule.

Une détection validée l'emporte sur toute autre lors de la fusion (M4, règle 1).
"""

from __future__ import annotations

import re
from datetime import date

# --- IBAN --------------------------------------------------------------------

LONGUEURS_IBAN: dict[str, int] = {
    # Zone UEMOA / CEDEAO — les pays visés par le projet
    "SN": 28, "BJ": 28, "TG": 28, "CI": 28, "BF": 28, "ML": 28, "NE": 28,
    "GW": 28, "CM": 27, "GA": 27, "CD": 27,
    # Zone euro fréquente dans les contrats
    "FR": 27, "BE": 16, "DE": 22, "ES": 24, "IT": 27, "PT": 25, "NL": 18,
    "LU": 20, "CH": 21, "GB": 22, "MA": 28, "TN": 24, "DZ": 26,
}


def iban_valide(valeur: str) -> bool:
    """Contrôle de clé IBAN : réarrangement puis mod-97 == 1 (ISO 13616)."""
    compact = re.sub(r"[\s-]", "", valeur).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", compact):
        return False

    pays = compact[:2]
    attendue = LONGUEURS_IBAN.get(pays)
    if attendue is not None and len(compact) != attendue:
        return False

    reagence = compact[4:] + compact[:4]
    numerique = "".join(
        str(ord(c) - 55) if c.isalpha() else c for c in reagence
    )
    # Modulo par tranches : évite de manipuler un entier de 30 chiffres.
    reste = 0
    for chiffre in numerique:
        reste = (reste * 10 + int(chiffre)) % 97
    return reste == 1


# --- Carte bancaire ----------------------------------------------------------


def luhn_valide(valeur: str) -> bool:
    """Contrôle de Luhn (ISO/IEC 7812) sur un numéro de 13 à 19 chiffres."""
    chiffres = re.sub(r"[\s.-]", "", valeur)
    if not chiffres.isdigit() or not (13 <= len(chiffres) <= 19):
        return False
    if len(set(chiffres)) == 1:
        return False  # 0000..., 1111... : jamais un vrai PAN

    total = 0
    for index, caractere in enumerate(reversed(chiffres)):
        chiffre = int(caractere)
        if index % 2 == 1:
            chiffre *= 2
            if chiffre > 9:
                chiffre -= 9
        total += chiffre
    return total % 10 == 0


# --- Téléphone ---------------------------------------------------------------

# Longueur nationale (hors indicatif) par indicatif pays, pour la zone visée.
LONGUEURS_NATIONALES: dict[str, set[int]] = {
    "221": {9},        # Sénégal
    "229": {8, 10},    # Bénin (passé à 10 chiffres en 2024)
    "228": {8},        # Togo
    "225": {10},       # Côte d'Ivoire
    "233": {9},        # Ghana
    "226": {8},        # Burkina Faso
    "223": {8},        # Mali
    "227": {8},        # Niger
    "234": {10},       # Nigéria
    "33": {9},         # France
}

PREFIXES_MOBILES_LOCAUX: dict[str, tuple[str, ...]] = {
    "221": ("70", "75", "76", "77", "78"),
    "229": ("01", "40", "41", "42", "43", "44", "45", "46", "47", "48", "49",
            "50", "51", "52", "53", "54", "55", "56", "57", "58", "59",
            "60", "61", "62", "63", "64", "65", "66", "67", "68", "69",
            "90", "91", "92", "93", "94", "95", "96", "97", "98", "99"),
    "228": ("70", "71", "72", "79", "90", "91", "92", "93", "96", "97", "98", "99"),
    "225": ("01", "05", "07", "25", "27"),
    "233": ("20", "23", "24", "26", "27", "50", "54", "55", "56", "57", "59"),
}


def telephone_valide(valeur: str) -> bool:
    """Vérifie la longueur nationale d'un numéro selon son indicatif.

    Sans indicatif explicite, on accepte 8 à 10 chiffres : c'est la plage
    couverte par les pays de la zone. Le contexte tranchera à la fusion.
    """
    compact = re.sub(r"[\s.\-()/]", "", valeur)
    if compact.startswith("00"):
        compact = "+" + compact[2:]

    if compact.startswith("+"):
        chiffres = compact[1:]
        if not chiffres.isdigit():
            return False
        for indicatif, longueurs in sorted(
            LONGUEURS_NATIONALES.items(), key=lambda kv: -len(kv[0])
        ):
            if chiffres.startswith(indicatif):
                return len(chiffres) - len(indicatif) in longueurs
        return 8 <= len(chiffres) <= 15

    if not compact.isdigit():
        return False
    return 8 <= len(compact) <= 10


# --- Date de naissance -------------------------------------------------------

MOIS_FR: dict[str, int] = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}

ANNEE_MIN = 1900


def date_naissance_valide(valeur: str, aujourdhui: date | None = None) -> bool:
    """Valide une date de naissance : date réelle, entre 1900 et aujourd'hui."""
    reference = aujourdhui or date.today()
    analysee = analyser_date(valeur)
    if analysee is None:
        return False
    return analysee.year >= ANNEE_MIN and analysee <= reference


def analyser_date(valeur: str) -> date | None:
    """Analyse les formats numériques `jj/mm/aaaa` et le format textuel FR."""
    texte = valeur.strip().lower()

    numerique = re.fullmatch(
        r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})", texte
    )
    if numerique:
        jour, mois, annee = (int(g) for g in numerique.groups())
        if annee < 100:
            annee += 1900 if annee > 30 else 2000
        return _date_ou_none(annee, mois, jour)

    textuelle = re.fullmatch(
        r"(\d{1,2})(?:er)?\s+([a-zéûôà]+)\s+(\d{4})", texte, flags=re.IGNORECASE
    )
    if textuelle:
        jour = int(textuelle.group(1))
        mois = MOIS_FR.get(textuelle.group(2))
        annee = int(textuelle.group(3))
        if mois is None:
            return None
        return _date_ou_none(annee, mois, jour)

    iso = re.fullmatch(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", texte)
    if iso:
        annee, mois, jour = (int(g) for g in iso.groups())
        return _date_ou_none(annee, mois, jour)

    return None


def _date_ou_none(annee: int, mois: int, jour: int) -> date | None:
    try:
        return date(annee, mois, jour)
    except ValueError:
        return None


# --- Pièces d'identité nationales -------------------------------------------

# Formats déclarés par pays : (longueur attendue, préfixes acceptés).
# Sénégal : NIN 13 chiffres commençant par 1 ou 2 (siècle de naissance).
# Bénin  : NPI 10 chiffres. Togo : NIF 13 chiffres. Côte d'Ivoire : CNI 11 car.
FORMATS_PIECE: dict[str, tuple[set[int], tuple[str, ...]]] = {
    "SN": ({13}, ("1", "2")),
    "BJ": ({10}, ()),
    "TG": ({13}, ()),
    "CI": ({11}, ("C",)),
}


def piece_identite_valide(valeur: str, pays: str | None = None) -> bool:
    """Valide un numéro de pièce d'identité par longueur et préfixe."""
    compact = re.sub(r"[\s.\-]", "", valeur).upper()
    if len(compact) < 8:
        return False

    formats = (
        [FORMATS_PIECE[pays]] if pays in FORMATS_PIECE else list(FORMATS_PIECE.values())
    )
    for longueurs, prefixes in formats:
        if len(compact) not in longueurs:
            continue
        if prefixes and not compact.startswith(prefixes):
            continue
        return True
    return False
