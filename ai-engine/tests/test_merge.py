"""Fusion des chevauchements — cas construits à la main (critère M4).

Chaque test isole exactement une règle de l'ordre d'arbitrage.
"""

from __future__ import annotations

from app.detection.merge import fusionner
from app.models import Entite, MethodeDetect


def entite(
    type_entite: str,
    debut: int,
    fin: int,
    *,
    valide: bool = False,
    score: float = 0.5,
    methode: MethodeDetect = MethodeDetect.regle,
) -> Entite:
    return Entite(
        typeEntite=type_entite,
        valeur="x" * (fin - debut),
        debut=debut,
        fin=fin,
        score=score,
        methode=methode,
        valide=valide,
    )


def test_aucun_chevauchement_tout_est_conserve() -> None:
    resultat = fusionner(
        [entite("EMAIL", 0, 10), entite("TELEPHONE", 20, 32)]
    )
    assert len(resultat) == 2


def test_regle_1_la_detection_validee_gagne() -> None:
    """Un IBAN validé par mod-97 l'emporte sur un empan plus large non validé."""
    validee = entite("IBAN", 10, 38, valide=True, score=0.6)
    large = entite("NUM_PIECE_IDENTITE", 5, 45, valide=False, score=0.99)

    resultat = fusionner([large, validee])

    assert len(resultat) == 1
    assert resultat[0].typeEntite == "IBAN"


def test_regle_2_a_validite_egale_le_plus_large_gagne() -> None:
    court = entite("NOM_PERSONNE", 10, 15, score=0.99)
    long = entite("ADRESSE_POSTALE", 8, 40, score=0.51)

    resultat = fusionner([court, long])

    assert len(resultat) == 1
    assert resultat[0].typeEntite == "ADRESSE_POSTALE"


def test_regle_3_a_empan_egal_le_meilleur_score_gagne() -> None:
    faible = entite("ORGANISATION", 0, 12, score=0.55)
    fort = entite("NOM_PERSONNE", 0, 12, score=0.95)

    resultat = fusionner([faible, fort])

    assert len(resultat) == 1
    assert resultat[0].typeEntite == "NOM_PERSONNE"


def test_regle_4_egalite_residuelle_on_conserve_les_deux() -> None:
    """Priorité au rappel : quand rien ne départage, on protège davantage."""
    a = entite("NOM_PERSONNE", 0, 12, score=0.80)
    b = entite("ORGANISATION", 6, 18, score=0.80)

    resultat = fusionner([a, b])

    assert len(resultat) == 2
    assert {e.typeEntite for e in resultat} == {"NOM_PERSONNE", "ORGANISATION"}


def test_doublon_exact_est_deduplique() -> None:
    a = entite("EMAIL", 0, 20, score=0.9)
    b = entite("EMAIL", 0, 20, score=0.9)

    resultat = fusionner([a, b])

    assert len(resultat) == 1


def test_corroboration_inter_familles_marque_la_methode_fusion() -> None:
    regle = entite("NOM_PERSONNE", 0, 11, score=0.8, methode=MethodeDetect.regle)
    modele = entite("NOM_PERSONNE", 0, 11, score=0.8, methode=MethodeDetect.ner)

    resultat = fusionner([regle, modele])

    assert len(resultat) == 1
    assert resultat[0].methode == MethodeDetect.fusion


def test_fenetres_de_segmentation_ne_produisent_pas_de_doublon() -> None:
    """Une entité vue deux fois à la frontière d'une fenêtre est fusionnée."""
    vue_fenetre_1 = entite("NOM_PERSONNE", 500, 511, score=0.85, methode=MethodeDetect.ner)
    vue_fenetre_2 = entite("NOM_PERSONNE", 500, 511, score=0.85, methode=MethodeDetect.ner)

    assert len(fusionner([vue_fenetre_1, vue_fenetre_2])) == 1


def test_resultat_trie_par_position() -> None:
    resultat = fusionner(
        [entite("EMAIL", 50, 60), entite("IBAN", 0, 28, valide=True), entite("TELEPHONE", 30, 42)]
    )
    assert [e.debut for e in resultat] == [0, 30, 50]


def test_chaine_de_trois_chevauchements() -> None:
    """Le plus fort absorbe ses concurrents, y compris en cascade."""
    faible_gauche = entite("ORGANISATION", 0, 10, score=0.6)
    dominant = entite("IBAN", 5, 35, valide=True, score=0.99)
    faible_droite = entite("NUM_CLIENT", 30, 40, score=0.6)

    resultat = fusionner([faible_gauche, dominant, faible_droite])

    assert len(resultat) == 1
    assert resultat[0].typeEntite == "IBAN"


def test_liste_vide() -> None:
    assert fusionner([]) == []
