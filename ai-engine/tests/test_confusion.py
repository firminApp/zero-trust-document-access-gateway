"""Matrice de confusion.

Ce que la matrice apporte, et que précision/rappel ne disent pas : la
distinction entre une donnée **manquée** (fuite) et une donnée **trouvée mais
mal étiquetée** (protégée quand même, au mauvais niveau). Les deux comptent
pareil dans le rappel ; elles n'ont rien à voir du point de vue du risque.
"""

from __future__ import annotations

import pytest

from evaluation.metrics import (
    MANQUEE,
    SUPERFLUE,
    Empan,
    apparier_par_position,
    matrice_confusion,
    sous_classements,
)


def empan(type_entite: str, debut: int, fin: int, niveau: str = "moyen") -> Empan:
    return Empan(type_entite, debut, fin, niveau)


# --- Appariement par position ------------------------------------------------


def test_apparie_deux_types_differents_au_meme_endroit() -> None:
    """Le point de départ : `apparier` ne verrait qu'un FN et un FP."""
    apparies, manquees, superflues = apparier_par_position(
        [empan("IBAN", 10, 38, "critique")],
        [empan("NUM_PIECE_IDENTITE", 10, 38, "critique")],
    )

    assert len(apparies) == 1
    assert apparies[0][0].type_entite == "IBAN"
    assert apparies[0][1].type_entite == "NUM_PIECE_IDENTITE"
    assert manquees == []
    assert superflues == []


def test_departage_par_recouvrement_le_meilleur_candidat() -> None:
    reference = [empan("NOM_PERSONNE", 10, 20)]
    prediction = [empan("ORGANISATION", 0, 12), empan("NOM_PERSONNE", 10, 20)]

    apparies, _, superflues = apparier_par_position(reference, prediction)

    assert len(apparies) == 1
    assert apparies[0][1].type_entite == "NOM_PERSONNE"   # recouvrement 1,0
    assert superflues[0].type_entite == "ORGANISATION"    # recouvrement partiel


def test_appariement_exclusif() -> None:
    apparies, manquees, _ = apparier_par_position(
        [empan("NOM_PERSONNE", 0, 10), empan("NOM_PERSONNE", 12, 22)],
        [empan("NOM_PERSONNE", 0, 22)],
    )
    assert len(apparies) == 1
    assert len(manquees) == 1


def test_mode_strict_exige_les_memes_frontieres() -> None:
    apparies, manquees, superflues = apparier_par_position(
        [empan("EMAIL", 10, 30)], [empan("EMAIL", 11, 30)], strict=True
    )
    assert apparies == []
    assert len(manquees) == 1
    assert len(superflues) == 1


def test_aucun_chevauchement_aucun_appariement() -> None:
    apparies, manquees, superflues = apparier_par_position(
        [empan("EMAIL", 0, 10)], [empan("EMAIL", 50, 60)]
    )
    assert apparies == []
    assert len(manquees) == 1
    assert len(superflues) == 1


# --- Matrice -----------------------------------------------------------------


def test_diagonale_pour_une_detection_parfaite() -> None:
    entites = [empan("IBAN", 0, 28, "critique"), empan("EMAIL", 40, 60)]
    matrice = matrice_confusion([entites], [entites])

    assert matrice.cellules["IBAN"]["IBAN"] == 1
    assert matrice.cellules["EMAIL"]["EMAIL"] == 1
    assert matrice.diagonale() == 2
    assert matrice.hors_diagonale() == 0


def test_confusion_de_type_apparait_hors_diagonale() -> None:
    matrice = matrice_confusion(
        [[empan("IBAN", 0, 28, "critique")]],
        [[empan("NUM_PIECE_IDENTITE", 0, 28, "critique")]],
    )

    assert matrice.cellules["IBAN"]["NUM_PIECE_IDENTITE"] == 1
    assert matrice.cellules["IBAN"].get(MANQUEE, 0) == 0
    assert matrice.hors_diagonale() == 1


def test_entite_manquee_va_dans_la_colonne_manquee() -> None:
    matrice = matrice_confusion([[empan("IBAN", 0, 28, "critique")]], [[]])

    assert matrice.cellules["IBAN"][MANQUEE] == 1
    # Une entité manquée n'est pas une confusion de type.
    assert matrice.hors_diagonale() == 0


def test_prediction_sans_reference_va_dans_la_ligne_superflue() -> None:
    matrice = matrice_confusion([[]], [[empan("ORGANISATION", 0, 10, "faible")]])
    assert matrice.cellules[SUPERFLUE]["ORGANISATION"] == 1


def test_les_totaux_de_ligne_valent_le_support() -> None:
    references = [
        [empan("EMAIL", 0, 10), empan("EMAIL", 20, 30), empan("IBAN", 40, 68, "critique")]
    ]
    predictions = [[empan("EMAIL", 0, 10), empan("NOM_PERSONNE", 20, 30)]]
    matrice = matrice_confusion(references, predictions)

    assert matrice.total_ligne("EMAIL") == 2
    assert matrice.total_ligne("IBAN") == 1


def test_confusions_listees_par_frequence() -> None:
    references = [
        [empan("ORGANISATION", 0, 10, "faible"), empan("LOCALITE", 20, 30, "faible")]
    ]
    predictions = [[empan("NOM_PERSONNE", 0, 10), empan("NOM_PERSONNE", 20, 30)]]
    matrice = matrice_confusion(references, predictions)

    confusions = matrice.confusions()
    assert ("ORGANISATION", "NOM_PERSONNE", 1) in confusions
    assert ("LOCALITE", "NOM_PERSONNE", 1) in confusions


def test_documents_desalignes_refuses() -> None:
    with pytest.raises(ValueError):
        matrice_confusion([[]], [[], []])


# --- Sous-classements : la lecture sécurité ----------------------------------


def test_sous_classement_detecte() -> None:
    """`critique` vue comme `moyen` : la donnée devient lisible par un rôle qui
    ne devrait pas y accéder. C'est la faille que M5 interdit."""
    matrice = matrice_confusion(
        [[empan("IBAN", 0, 28, "critique")]],
        [[empan("EMAIL", 0, 28, "moyen")]],
        par_niveau=True,
    )

    assert sous_classements(matrice) == [("critique", "moyen", 1)]


def test_sur_classement_n_est_pas_un_sous_classement() -> None:
    # Masquer trop est une gêne opérationnelle, pas une faille.
    matrice = matrice_confusion(
        [[empan("EMAIL", 0, 20, "moyen")]],
        [[empan("IBAN", 0, 20, "critique")]],
        par_niveau=True,
    )
    assert sous_classements(matrice) == []


def test_entite_manquee_n_est_pas_comptee_comme_sous_classement() -> None:
    # Elle est déjà comptée par le rappel ; l'imputer deux fois fausserait la
    # lecture de la matrice.
    matrice = matrice_confusion(
        [[empan("IBAN", 0, 28, "critique")]], [[]], par_niveau=True
    )
    assert sous_classements(matrice) == []
    assert matrice.cellules["critique"][MANQUEE] == 1


def test_sous_classements_ordonnes_du_plus_grave() -> None:
    references = [
        [empan("IBAN", 0, 28, "critique"), empan("TELEPHONE", 40, 57, "eleve")]
    ]
    predictions = [
        [
            empan("EMAIL", 0, 28, "moyen"),        # critique -> moyen
            empan("LOCALITE", 40, 57, "faible"),   # eleve    -> faible
        ]
    ]
    matrice = matrice_confusion(references, predictions, par_niveau=True)

    releves = sous_classements(matrice)
    assert releves[0][0] == "critique"   # le plus grave d'abord
    assert releves[1][0] == "eleve"


def test_niveau_identique_type_different_nest_pas_un_sous_classement() -> None:
    matrice = matrice_confusion(
        [[empan("EMAIL", 0, 20, "moyen")]],
        [[empan("NOM_PERSONNE", 0, 20, "moyen")]],
        par_niveau=True,
    )
    assert sous_classements(matrice) == []
    assert matrice.cellules["moyen"]["moyen"] == 1
