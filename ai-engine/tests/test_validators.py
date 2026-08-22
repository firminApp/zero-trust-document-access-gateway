"""Validateurs : tests positifs ET négatifs (critère d'acceptation M4).

Le cas négatif est le plus important : c'est lui qui prouve que le validateur
apporte de la spécificité. Un IBAN à clé fausse doit être rejeté, sinon le
validateur ne fait que valider le motif.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.detection import validators

# --- IBAN --------------------------------------------------------------------

IBAN_VALIDES = [
    "SN91SN0100152000048500000765",
    "FR7630006000011234567890189",
    "BE68539007547034",
    "DE89370400440532013000",
    "SN91 SN01 0015 2000 0485 0000 0765",  # espaces tolérés
]

IBAN_INVALIDES = [
    "SN92SN0100152000048500000765",   # clé de contrôle fausse (91 -> 92)
    "FR7630006000011234567890188",    # dernier chiffre modifié
    "BE68539007547035",               # clé fausse
    "XX0812345678901234567890",       # pays inconnu, clé fausse
    "FR76300060000112345678901",      # longueur FR incorrecte
    "SN08",                           # tronqué
    "pas un iban du tout",
]


@pytest.mark.parametrize("valeur", IBAN_VALIDES)
def test_iban_valide(valeur: str) -> None:
    assert validators.iban_valide(valeur) is True


@pytest.mark.parametrize("valeur", IBAN_INVALIDES)
def test_iban_invalide(valeur: str) -> None:
    assert validators.iban_valide(valeur) is False


def test_iban_cle_fausse_sur_chaque_variante() -> None:
    """Modifier un seul chiffre de contrôle doit invalider l'IBAN."""
    base = "SN91SN0100152000048500000765"
    assert validators.iban_valide(base)
    for remplacement in "1234567890":
        altere = base[:2] + "0" + remplacement + base[4:]
        if altere == base:
            continue
        assert validators.iban_valide(altere) is False, altere


# --- Luhn / carte bancaire ---------------------------------------------------

CARTES_VALIDES = [
    "4539578763621486",
    "4539 5787 6362 1486",
    "5500005555555559",
    "378282246310005",       # Amex, 15 chiffres
]

CARTES_INVALIDES = [
    "4539578763621487",      # dernier chiffre modifié
    "1234567812345678",
    "0000000000000000",      # chiffres identiques
    "4539578763",            # trop court
    "45395787636214861234",  # trop long
    "abcd efgh ijkl mnop",
]


@pytest.mark.parametrize("valeur", CARTES_VALIDES)
def test_luhn_valide(valeur: str) -> None:
    assert validators.luhn_valide(valeur) is True


@pytest.mark.parametrize("valeur", CARTES_INVALIDES)
def test_luhn_invalide(valeur: str) -> None:
    assert validators.luhn_valide(valeur) is False


# --- Téléphone ---------------------------------------------------------------

TELEPHONES_VALIDES = [
    "+221771234567",         # Sénégal, 9 chiffres
    "+221 77 123 45 67",
    "+22997123456",          # Bénin, 8 chiffres
    "+2290197123456",        # Bénin, 10 chiffres (numérotation 2024)
    "+22890123456",          # Togo
    "+2250701234567",        # Côte d'Ivoire, 10 chiffres
    "+233241234567",         # Ghana
    "00221771234567",        # préfixe international 00
    "77 123 45 67",          # format local
]

TELEPHONES_INVALIDES = [
    "+22177123",             # Sénégal trop court
    "+2217712345678901",     # trop long
    "+22997",                # tronqué
    "12345",                 # trop court
    "+221abcdefghi",
]


@pytest.mark.parametrize("valeur", TELEPHONES_VALIDES)
def test_telephone_valide(valeur: str) -> None:
    assert validators.telephone_valide(valeur) is True


@pytest.mark.parametrize("valeur", TELEPHONES_INVALIDES)
def test_telephone_invalide(valeur: str) -> None:
    assert validators.telephone_valide(valeur) is False


# --- Date de naissance -------------------------------------------------------

REFERENCE = date(2026, 1, 1)

DATES_VALIDES = ["03/07/1988", "3-7-1988", "12 mars 1990", "1er janvier 1975", "1988-07-03"]

DATES_INVALIDES = [
    "32/01/1990",   # jour inexistant
    "29/02/1991",   # 1991 n'est pas bissextile
    "03/07/1850",   # antérieur à 1900
    "03/07/2099",   # dans le futur
    "13 blurp 1990",
    "pas une date",
]


@pytest.mark.parametrize("valeur", DATES_VALIDES)
def test_date_naissance_valide(valeur: str) -> None:
    assert validators.date_naissance_valide(valeur, REFERENCE) is True


@pytest.mark.parametrize("valeur", DATES_INVALIDES)
def test_date_naissance_invalide(valeur: str) -> None:
    assert validators.date_naissance_valide(valeur, REFERENCE) is False


def test_annee_sur_deux_chiffres() -> None:
    assert validators.analyser_date("03/07/88") == date(1988, 7, 3)
    assert validators.analyser_date("03/07/05") == date(2005, 7, 3)


# --- Pièce d'identité --------------------------------------------------------


@pytest.mark.parametrize(
    "valeur,pays",
    [
        ("1988070312345", "SN"),   # NIN sénégalais : 13 chiffres, préfixe 1
        ("2990120145678", "SN"),
        ("0123456789", "BJ"),      # NPI béninois : 10 chiffres
        ("1234567890123", "TG"),
        ("C01234567891"[:11], "CI"),
    ],
)
def test_piece_identite_valide(valeur: str, pays: str) -> None:
    assert validators.piece_identite_valide(valeur, pays) is True


@pytest.mark.parametrize(
    "valeur,pays",
    [
        ("3988070312345", "SN"),   # préfixe interdit
        ("198807031234", "SN"),    # 12 chiffres
        ("012345678", "BJ"),       # 9 chiffres
        ("123", None),             # trop court
    ],
)
def test_piece_identite_invalide(valeur: str, pays: str | None) -> None:
    assert validators.piece_identite_valide(valeur, pays) is False
