"""Détection par règles sur des extraits réalistes."""

from __future__ import annotations

from app.detection.rules import detecter


def types_de(texte: str) -> set[str]:
    return {e.typeEntite for e in detecter(texte)}


def valeurs_de(texte: str, type_entite: str) -> set[str]:
    return {e.valeur for e in detecter(texte) if e.typeEntite == type_entite}


def test_email() -> None:
    assert "awa.diouf@exemple.sn" in valeurs_de(
        "Contacter awa.diouf@exemple.sn pour la suite.", "EMAIL"
    )


def test_telephones_de_la_zone_cedeao() -> None:
    texte = (
        "Sénégal +221 77 123 45 67, Bénin +229 97 12 34 56, "
        "Togo +228 90 12 34 56, Côte d'Ivoire +225 07 01 23 45 67, "
        "Ghana +233 24 123 4567."
    )
    assert len(valeurs_de(texte, "TELEPHONE")) >= 5


def test_iban_valide_detecte_et_marque_valide() -> None:
    entites = [
        e
        for e in detecter("RIB : SN91SN0100152000048500000765")
        if e.typeEntite == "IBAN"
    ]
    assert len(entites) == 1
    assert entites[0].valide is True


def test_iban_a_cle_fausse_est_rejete() -> None:
    """Le validateur, pas le motif, fait la spécificité."""
    assert "IBAN" not in types_de("RIB : SN92SN0100152000048500000765")


def test_carte_bancaire_luhn() -> None:
    assert "CARTE_BANCAIRE" in types_de("Carte 4539 5787 6362 1486")
    assert "CARTE_BANCAIRE" not in types_de("Commande 4539 5787 6362 1487")


def test_date_de_naissance_numerique_et_textuelle() -> None:
    assert "DATE_NAISSANCE" in types_de("Né le 03/07/1988 à Thiès")
    assert "DATE_NAISSANCE" in types_de("Née le 12 mars 1990 à Cotonou")


def test_date_impossible_est_rejetee() -> None:
    assert "DATE_NAISSANCE" not in types_de("Référence 32/13/1990")


def test_piece_identite_par_format_national() -> None:
    assert "NUM_PIECE_IDENTITE" in types_de("NIN 1988070312345")


def test_piece_identite_par_indice_lexical() -> None:
    """Un numéro hors format national passe s'il est annoncé comme une pièce."""
    assert "NUM_PIECE_IDENTITE" in types_de("Passeport n° A00123456")


def test_nombre_isole_sans_indice_nest_pas_une_piece() -> None:
    assert "NUM_PIECE_IDENTITE" not in types_de("Montant total : 123456789 FCFA")


def test_plaque_immatriculation() -> None:
    assert "PLAQUE_IMMAT" in types_de("Véhicule immatriculé DK-4521-AB")


def test_numero_client() -> None:
    valeurs = valeurs_de("Référence client : GZ-889201", "NUM_CLIENT")
    assert "GZ-889201" in valeurs


def test_document_complet() -> None:
    texte = (
        "ATTESTATION\n"
        "Je soussigné Mamadou FALL, né le 03/07/1988 à Thiès,\n"
        "titulaire de la CNI n° 1988070312345,\n"
        "domicilié 12 rue Félix Faure, Dakar,\n"
        "courriel mamadou.fall@exemple.sn, téléphone +221 77 555 44 33,\n"
        "IBAN SN91SN0100152000048500000765.\n"
    )
    trouves = types_de(texte)
    for attendu in (
        "EMAIL",
        "TELEPHONE",
        "IBAN",
        "DATE_NAISSANCE",
        "NUM_PIECE_IDENTITE",
    ):
        assert attendu in trouves, attendu


def test_texte_sans_donnee_personnelle() -> None:
    assert detecter("Le ciel est bleu et la procédure est close.") == []
