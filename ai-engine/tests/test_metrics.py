"""Métriques d'évaluation — le F2 est la métrique de décision."""

from __future__ import annotations

from evaluation.metrics import Empan, Scores, apparier, cer, evaluer


def empan(type_entite: str, debut: int, fin: int, niveau: str = "moyen") -> Empan:
    return Empan(type_entite, debut, fin, niveau)


def test_scores_parfaits() -> None:
    scores = Scores(vp=10, fp=0, fn=0)
    assert scores.precision == 1.0
    assert scores.rappel == 1.0
    assert scores.f1 == 1.0
    assert scores.f2 == 1.0


def test_f2_pondere_le_rappel_plus_que_la_precision() -> None:
    """C'est la propriété qui justifie le choix du F2 (ADR n°5)."""
    beaucoup_de_faux_positifs = Scores(vp=90, fp=60, fn=10)   # R=0,90  P=0,60
    beaucoup_de_faux_negatifs = Scores(vp=60, fp=10, fn=40)   # R=0,60  P=0,857

    # Le F1 place les deux presque à égalité...
    assert abs(beaucoup_de_faux_positifs.f1 - beaucoup_de_faux_negatifs.f1) < 0.03
    # ...le F2 tranche nettement en faveur du rappel.
    assert beaucoup_de_faux_positifs.f2 > beaucoup_de_faux_negatifs.f2 + 0.15


def test_scores_degenerés() -> None:
    assert Scores().precision == 0.0
    assert Scores().rappel == 0.0
    assert Scores().f2 == 0.0


def test_support_est_le_nombre_de_references() -> None:
    assert Scores(vp=7, fp=3, fn=2).support == 9


# --- Appariement -------------------------------------------------------------


def test_appariement_strict_exige_les_memes_frontieres() -> None:
    reference = [empan("EMAIL", 10, 30)]
    prediction = [empan("EMAIL", 10, 29)]

    apparies, manquees, superflues = apparier(reference, prediction, strict=True)
    assert apparies == []
    assert len(manquees) == 1
    assert len(superflues) == 1


def test_appariement_partiel_accepte_un_chevauchement() -> None:
    reference = [empan("EMAIL", 10, 30)]
    prediction = [empan("EMAIL", 12, 28)]

    apparies, manquees, superflues = apparier(reference, prediction, strict=False)
    assert len(apparies) == 1
    assert manquees == []
    assert superflues == []


def test_un_type_different_nest_jamais_apparie() -> None:
    apparies, manquees, superflues = apparier(
        [empan("IBAN", 0, 28)], [empan("NUM_PIECE_IDENTITE", 0, 28)], strict=False
    )
    assert apparies == []
    assert len(manquees) == 1
    assert len(superflues) == 1


def test_appariement_exclusif() -> None:
    """Un empan large ne doit pas valider deux références d'un coup."""
    reference = [empan("NOM_PERSONNE", 0, 10), empan("NOM_PERSONNE", 12, 22)]
    prediction = [empan("NOM_PERSONNE", 0, 22)]

    apparies, manquees, superflues = apparier(reference, prediction, strict=False)
    assert len(apparies) == 1
    assert len(manquees) == 1
    assert superflues == []


# --- Évaluation complète -----------------------------------------------------


def test_evaluation_ventilee_par_type_et_par_niveau() -> None:
    references = [
        [empan("EMAIL", 0, 20), empan("IBAN", 30, 58, "critique")],
        [empan("IBAN", 5, 33, "critique")],
    ]
    predictions = [
        [empan("EMAIL", 0, 20), empan("IBAN", 30, 58, "critique")],
        [empan("TELEPHONE", 60, 77, "eleve")],  # 1 FN sur IBAN, 1 FP sur TELEPHONE
    ]

    rapport = evaluer(references, predictions, strict=True)

    assert rapport.global_.vp == 2
    assert rapport.global_.fn == 1
    assert rapport.global_.fp == 1
    assert rapport.par_type["IBAN"].as_dict()["rappel"] == 0.5
    assert rapport.par_type["EMAIL"].as_dict()["rappel"] == 1.0
    assert rapport.par_niveau["critique"].support == 2


def test_le_rappel_global_peut_masquer_un_type_defaillant() -> None:
    """Le piège n°10, rendu explicite par un test."""
    references = [
        [empan("EMAIL", i * 10, i * 10 + 5) for i in range(9)]
        + [empan("NUM_PIECE_IDENTITE", 200, 213, "critique")]
    ]
    predictions = [[empan("EMAIL", i * 10, i * 10 + 5) for i in range(9)]]

    rapport = evaluer(references, predictions, strict=True)

    assert rapport.global_.rappel == 0.9                       # « conforme » en apparence
    assert rapport.par_type["NUM_PIECE_IDENTITE"].rappel == 0.0  # angle mort réel


def test_documents_desalignes_sont_refuses() -> None:
    import pytest

    with pytest.raises(ValueError):
        evaluer([[]], [[], []])


# --- CER ---------------------------------------------------------------------


def test_cer_nul_sur_texte_identique() -> None:
    assert cer("Awa Diouf, Dakar", "Awa Diouf, Dakar") == 0.0


def test_cer_ignore_les_differences_d_espacement() -> None:
    assert cer("Awa  Diouf", "Awa Diouf") == 0.0


def test_cer_croit_avec_les_erreurs() -> None:
    faible = cer("Awa Diouf habite Dakar", "Awa Diouf habite Dakan")
    fort = cer("Awa Diouf habite Dakar", "Awo Diovf hobite Dokon")
    assert 0 < faible < fort


def test_cer_reference_vide() -> None:
    assert cer("", "") == 0.0
    assert cer("", "bruit") == 1.0
