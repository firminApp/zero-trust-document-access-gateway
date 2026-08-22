"""Classification par sensibilité (M5).

Critère d'acceptation : **zéro sous-classement**. Une donnée critique rangée
plus bas ouvre l'accès à un rôle qui ne devrait pas l'avoir — c'est une faille,
pas une imprécision. Le sur-classement, lui, est acceptable.
"""

from __future__ import annotations

import pytest

from app.classification.sensitivity import (
    ORDRE_NIVEAU,
    classer,
    niveau_de,
    niveau_maximum,
)
from app.models import Entite, NiveauSens

TYPES_CRITIQUES = ("NUM_PIECE_IDENTITE", "IBAN", "CARTE_BANCAIRE", "DONNEE_SANTE")


def entite(type_entite: str, debut: int = 0, fin: int = 10) -> Entite:
    return Entite(typeEntite=type_entite, valeur="x", debut=debut, fin=fin)


@pytest.mark.parametrize("type_entite", TYPES_CRITIQUES)
def test_aucun_sous_classement_des_types_critiques(type_entite: str) -> None:
    assert niveau_de(type_entite) == NiveauSens.critique


@pytest.mark.parametrize(
    "type_entite,attendu",
    [
        ("LOCALITE", NiveauSens.faible),
        ("ORGANISATION", NiveauSens.faible),
        ("NOM_PERSONNE", NiveauSens.moyen),
        ("ADRESSE_POSTALE", NiveauSens.moyen),
        ("EMAIL", NiveauSens.moyen),
        ("TELEPHONE", NiveauSens.eleve),
        ("DATE_NAISSANCE", NiveauSens.eleve),
        ("NUM_CLIENT", NiveauSens.eleve),
        ("IBAN", NiveauSens.critique),
    ],
)
def test_grille_de_base(type_entite: str, attendu: NiveauSens) -> None:
    assert niveau_de(type_entite) == attendu


def test_type_inconnu_ne_tombe_pas_au_plus_bas() -> None:
    """Un type non répertorié vaut `moyen`, jamais `faible` : refus par défaut."""
    assert niveau_de("TYPE_JAMAIS_VU") == NiveauSens.moyen


def test_ajustement_contextuel_eleve_le_nom_en_piece_identite() -> None:
    """Nom + date de naissance + n° de pièce à moins de 200 caractères."""
    entites = [
        entite("NOM_PERSONNE", 0, 11),
        entite("DATE_NAISSANCE", 40, 50),
        entite("NUM_PIECE_IDENTITE", 80, 93),
    ]
    classer(entites)
    assert entites[0].niveau == NiveauSens.eleve


def test_nom_isole_reste_moyen() -> None:
    entites = [entite("NOM_PERSONNE", 0, 11)]
    classer(entites)
    assert entites[0].niveau == NiveauSens.moyen


def test_nom_avec_un_seul_identifiant_reste_moyen() -> None:
    """Une seule co-occurrence est une mention, pas une pièce d'identité."""
    entites = [entite("NOM_PERSONNE", 0, 11), entite("DATE_NAISSANCE", 40, 50)]
    classer(entites)
    assert entites[0].niveau == NiveauSens.moyen


def test_identifiants_hors_fenetre_nelevent_pas_le_nom() -> None:
    entites = [
        entite("NOM_PERSONNE", 0, 11),
        entite("DATE_NAISSANCE", 900, 910),
        entite("NUM_PIECE_IDENTITE", 1200, 1213),
    ]
    classer(entites)
    assert entites[0].niveau == NiveauSens.moyen


def test_niveau_max_du_document() -> None:
    entites = [entite("LOCALITE"), entite("EMAIL", 20, 40), entite("IBAN", 50, 78)]
    classer(entites)
    assert niveau_maximum(entites) == NiveauSens.critique


def test_niveau_max_sans_entite_est_none() -> None:
    """Document sans DCP : `niveau_max` reste indéfini côté moteur."""
    assert niveau_maximum([]) is None


def test_ordre_des_niveaux() -> None:
    assert (
        ORDRE_NIVEAU[NiveauSens.faible]
        < ORDRE_NIVEAU[NiveauSens.moyen]
        < ORDRE_NIVEAU[NiveauSens.eleve]
        < ORDRE_NIVEAU[NiveauSens.critique]
    )
