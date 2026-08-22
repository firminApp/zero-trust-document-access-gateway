"""Appariement par valeur et rappel de bout en bout.

Sur un scan, les offsets de la vérité terrain et ceux des prédictions ne vivent
pas dans le même repère : l'OCR insère et supprime des caractères. L'appariement
se fait donc par valeur, avec une tolérance explicite.

Le cas qui compte est celui du validateur : un IBAN dont l'OCR abîme un seul
caractère échoue au contrôle mod-97 et disparaît. La précision parfaite du
validateur sur du texte propre devient la cause de la perte sur du texte
océrisé — et seule cette campagne le montre.
"""

from __future__ import annotations

from evaluation.metrics import (
    Empan,
    RapportE2E,
    apparier_par_valeur,
    cle_comparaison,
    presente_dans,
    similarite,
)


def empan(type_entite: str, niveau: str = "moyen") -> Empan:
    return Empan(type_entite, 0, 0, niveau)


# --- Forme canonique ---------------------------------------------------------


def test_canonisation_neutralise_casse_accents_et_ponctuation() -> None:
    assert cle_comparaison("Awa DIOUF") == cle_comparaison("awa diouf")
    assert cle_comparaison("Thérèse") == cle_comparaison("Therese")
    assert cle_comparaison("+221 77 123 45 67") == cle_comparaison("221771234567")


def test_canonisation_ne_replie_pas_les_confusions_ocr() -> None:
    """O/0 et I/1 restent distincts : les replier gonflerait le rappel."""
    assert cle_comparaison("SN0100") != cle_comparaison("SNO1OO")


# --- Similarité --------------------------------------------------------------


def test_similarite_parfaite_sur_valeurs_identiques() -> None:
    assert similarite("Awa Diouf", "awa  diouf") == 1.0


def test_similarite_decroit_avec_les_erreurs() -> None:
    proche = similarite("SN91SN0100152000048500000765", "SN91SN0100152000048500000766")
    lointain = similarite("SN91SN0100152000048500000765", "SN91SN01OO1S2OOOO48SOOOOO76S")
    assert 1.0 > proche > lointain


def test_similarite_nulle_sur_valeur_vide() -> None:
    assert similarite("", "Awa Diouf") == 0.0
    assert similarite("", "") == 1.0


# --- Appariement par valeur --------------------------------------------------


def test_apparie_une_valeur_exacte() -> None:
    apparies, manquees, superflues = apparier_par_valeur(
        [empan("EMAIL")], [empan("EMAIL")], ["awa@exemple.sn"], ["awa@exemple.sn"]
    )
    assert len(apparies) == 1
    assert manquees == []
    assert superflues == []


def test_apparie_malgre_le_bruit_ocr_sous_la_tolerance() -> None:
    apparies, _, _ = apparier_par_valeur(
        [empan("NOM_PERSONNE")],
        [empan("NOM_PERSONNE")],
        ["Mamadou FALL"],
        ["Mamadou FALI"],   # un caractère abîmé
        tolerance=0.25,
    )
    assert len(apparies) == 1


def test_n_apparie_pas_au_dela_de_la_tolerance() -> None:
    apparies, manquees, _ = apparier_par_valeur(
        [empan("NOM_PERSONNE")],
        [empan("NOM_PERSONNE")],
        ["Mamadou FALL"],
        ["Xyzabcd QRST"],
        tolerance=0.25,
    )
    assert apparies == []
    assert manquees == [0]


def test_tolerance_nulle_exige_une_correspondance_exacte() -> None:
    apparies, manquees, _ = apparier_par_valeur(
        [empan("IBAN", "critique")],
        [empan("IBAN", "critique")],
        ["SN91SN0100152000048500000765"],
        ["SN91SN0100152000048500000766"],
        tolerance=0.0,
    )
    assert apparies == []
    assert manquees == [0]


def test_le_type_doit_correspondre_par_defaut() -> None:
    apparies, manquees, superflues = apparier_par_valeur(
        [empan("IBAN", "critique")],
        [empan("NUM_PIECE_IDENTITE", "critique")],
        ["SN91SN0100152000048500000765"],
        ["SN91SN0100152000048500000765"],
    )
    assert apparies == []
    assert len(manquees) == 1
    assert len(superflues) == 1


def test_appariement_exclusif_sur_valeurs_repetees() -> None:
    """Deux occurrences attendues, une seule trouvée : un seul appariement."""
    apparies, manquees, _ = apparier_par_valeur(
        [empan("EMAIL"), empan("EMAIL")],
        [empan("EMAIL")],
        ["awa@exemple.sn", "awa@exemple.sn"],
        ["awa@exemple.sn"],
    )
    assert len(apparies) == 1
    assert len(manquees) == 1


def test_le_meilleur_candidat_est_apparie_en_premier() -> None:
    apparies, _, superflues = apparier_par_valeur(
        [empan("NOM_PERSONNE")],
        [empan("NOM_PERSONNE"), empan("NOM_PERSONNE")],
        ["Mamadou FALL"],
        ["Mamadou FALI", "Mamadou FALL"],
    )
    assert len(apparies) == 1
    assert apparies[0][1] == 1          # l'exact, pas l'approché
    assert superflues == [0]


# --- Diagnostic : OCR ou détection ? -----------------------------------------


def test_valeur_reconnaissable_dans_le_texte_ocerise() -> None:
    texte = "IBAN SN91SN0100152000048500000765 du titulaire"
    assert presente_dans(texte, "SN91SN0100152000048500000765") is True


def test_valeur_detruite_par_l_ocr_nest_pas_reconnaissable() -> None:
    texte = "IBAN ############ du titulaire"
    assert presente_dans(texte, "SN91SN0100152000048500000765") is False


def test_valeur_legerement_abimee_reste_reconnaissable() -> None:
    # C'est le cas qui distingue « perdue à l'OCR » de « non détectée » : la
    # valeur est là, lisible, mais le validateur mod-97 la rejettera.
    texte = "IBAN SN91SN0100152000048500000766 du titulaire"
    assert presente_dans(texte, "SN91SN0100152000048500000765") is True


# --- Accumulation ------------------------------------------------------------


def test_le_rappel_est_ventile_par_condition_type_et_niveau() -> None:
    rapport = RapportE2E()

    rapport.compter(
        "reference",
        [empan("IBAN", "critique"), empan("EMAIL", "moyen")],
        ["SN91SN0100152000048500000765", "awa@exemple.sn"],
        [empan("IBAN", "critique")],
        ["SN91SN0100152000048500000765"],
        "texte contenant SN91SN0100152000048500000765 seulement",
    )

    assert rapport.global_["reference"].rappel == 0.5
    assert rapport.par_type[("reference", "IBAN")].rappel == 1.0
    assert rapport.par_type[("reference", "EMAIL")].rappel == 0.0
    assert rapport.par_niveau[("reference", "critique")].rappel == 1.0


def test_perte_imputee_a_l_ocr_quand_la_valeur_a_disparu() -> None:
    rapport = RapportE2E()
    rapport.compter(
        "bruit",
        [empan("IBAN", "critique")],
        ["SN91SN0100152000048500000765"],
        [],
        [],
        "texte totalement illisible ###### ",
    )

    assert rapport.perdues_ocr[("bruit", "IBAN")] == 1
    assert rapport.non_detectees[("bruit", "IBAN")] == 0


def test_perte_imputee_a_la_detection_quand_la_valeur_est_lisible() -> None:
    """Le scénario du validateur : la valeur est là, un caractère est faux,
    mod-97 la rejette. Ce n'est pas l'OCR qui a perdu la donnée."""
    rapport = RapportE2E()
    rapport.compter(
        "flou",
        [empan("IBAN", "critique")],
        ["SN91SN0100152000048500000765"],
        [],
        [],
        "IBAN SN91SN0100152000048500000766 lisible mais invalide",
    )

    assert rapport.non_detectees[("flou", "IBAN")] == 1
    assert rapport.perdues_ocr[("flou", "IBAN")] == 0


def test_rappel_critique_minimal_prend_la_pire_condition() -> None:
    # La cible de 0,95 doit tenir sur la condition la plus défavorable : une
    # moyenne masquerait une condition où un IBAN sur deux passe en clair.
    rapport = RapportE2E()
    for condition, trouve in (("reference", True), ("bruit", False)):
        rapport.compter(
            condition,
            [empan("IBAN", "critique")],
            ["SN91SN0100152000048500000765"],
            [empan("IBAN", "critique")] if trouve else [],
            ["SN91SN0100152000048500000765"] if trouve else [],
            "SN91SN0100152000048500000765",
        )

    assert rapport.par_niveau[("reference", "critique")].rappel == 1.0
    assert rapport.rappel_critique_minimal() == 0.0


def test_conditions_listees_dans_l_ordre_du_protocole() -> None:
    rapport = RapportE2E()
    for condition in ("jpeg40", "reference", "bruit"):
        rapport.compter(condition, [], [], [], [], "")
    assert rapport.conditions == ["reference", "bruit", "jpeg40"]
