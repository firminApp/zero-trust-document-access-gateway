"""Protection et restitution (M6).

Le test le plus important du module est `test_pdf_le_texte_est_reellement_supprime` :
il vérifie le piège n°2 — un rectangle noir sans `apply_redactions()` laisse le
texte extractible dessous, ce qui est une fausse protection.
"""

from __future__ import annotations

import shutil

import pytest

from app import pipeline
from app.classification.sensitivity import au_moins
from app.extraction import router
from app.models import Entite, NiveauSens
from app.protection import crypt, mask, pseudonymize

OCR_DISPONIBLE = shutil.which("tesseract") is not None

CLE_TEST = "0" * 64  # 32 octets en hexadécimal


# --- Fabrication de la valeur masquée ----------------------------------------


def test_masquage_email_suit_le_format_documente() -> None:
    assert mask.masquer_valeur("jean.dupont@mail.com", "EMAIL") == "j••••••@••••"


def test_masquage_conserve_la_premiere_lettre_de_chaque_mot() -> None:
    assert mask.masquer_valeur("Jean Dupont", "NOM_PERSONNE") == "J••• D•••••"


def test_masquage_conserve_les_separateurs() -> None:
    assert mask.masquer_valeur("03/07/1988", "DATE_NAISSANCE") == "0•/0•/1•••"


def test_masquage_ne_laisse_aucun_chiffre_significatif_dans_un_iban() -> None:
    masque = mask.masquer_valeur("SN91SN0100152000048500000765", "IBAN")
    assert masque.count("•") >= 20
    assert "0100152000048500000765" not in masque


# --- Pseudonymisation --------------------------------------------------------


def test_pseudonyme_deterministe() -> None:
    a = pseudonymize.jeton("Jean Dupont", "NOM_PERSONNE", sel="sel")
    b = pseudonymize.jeton("Jean Dupont", "NOM_PERSONNE", sel="sel")
    assert a == b
    assert a.startswith("PERS-")
    assert len(a) == len("PERS-") + 4


def test_pseudonyme_insensible_a_la_casse_et_aux_accents() -> None:
    """Deux graphies de la même personne doivent donner le même jeton."""
    assert pseudonymize.jeton("Jean DUPONT", "NOM_PERSONNE", sel="s") == pseudonymize.jeton(
        "jean  dupont", "NOM_PERSONNE", sel="s"
    )


def test_pseudonymes_differents_pour_valeurs_differentes() -> None:
    a = pseudonymize.jeton("Jean Dupont", "NOM_PERSONNE", sel="sel")
    b = pseudonymize.jeton("Awa Diouf", "NOM_PERSONNE", sel="sel")
    assert a != b


def test_le_sel_change_le_jeton() -> None:
    """Sans sel serveur, un dictionnaire de patronymes casserait la protection."""
    assert pseudonymize.jeton("Jean Dupont", "NOM_PERSONNE", sel="a") != pseudonymize.jeton(
        "Jean Dupont", "NOM_PERSONNE", sel="b"
    )


def test_correspondance_est_reversible_avec_la_cle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AES_KEY", CLE_TEST)
    lien = pseudonymize.correspondance("Jean Dupont", "NOM_PERSONNE", sel="sel")
    assert lien.valeurChiffreeBase64 is not None

    import base64

    clair = crypt.dechiffrer(base64.b64decode(lien.valeurChiffreeBase64))
    assert clair.decode() == "Jean Dupont"


def test_correspondance_sans_cle_reste_deterministe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AES_KEY", raising=False)
    lien = pseudonymize.correspondance("Jean Dupont", "NOM_PERSONNE", sel="sel")
    assert lien.valeurChiffreeBase64 is None
    assert lien.jeton.startswith("PERS-")


# --- Chiffrement -------------------------------------------------------------


def test_aes_gcm_aller_retour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AES_KEY", CLE_TEST)
    cryptogramme = crypt.chiffrer(b"donnee sensible")
    assert b"donnee sensible" not in cryptogramme
    assert crypt.dechiffrer(cryptogramme) == b"donnee sensible"


def test_aes_gcm_detecte_l_alteration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AES_KEY", CLE_TEST)
    cryptogramme = bytearray(crypt.chiffrer(b"donnee sensible"))
    cryptogramme[-1] ^= 0x01
    with pytest.raises(Exception):
        crypt.dechiffrer(bytes(cryptogramme))


def test_sans_cle_le_chiffrement_est_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AES_KEY", raising=False)
    assert crypt.chiffrement_disponible() is False
    with pytest.raises(crypt.CleAbsente):
        crypt.chiffrer(b"x")


# --- Application par format --------------------------------------------------


def proteger(contenu: bytes, type_mime: str, nom: str | None = None,
             seuil: NiveauSens = NiveauSens.moyen) -> tuple[bytes, int]:
    extraction, entites, _ = pipeline.analyser(contenu, type_mime, nom)
    cibles = [e for e in entites if au_moins(e.niveau, seuil)]
    octets, nombre, _ = mask.appliquer(
        contenu,
        type_mime,
        nom,
        extraction,
        cibles,
        lambda e: mask.masquer_valeur(e.valeur, e.typeEntite),
    )
    return octets, nombre


def test_texte_les_valeurs_disparaissent(csv_simple: bytes) -> None:
    protege, nombre = proteger(csv_simple, "text/csv", "clients.csv")
    sortie = protege.decode("utf-8")

    assert nombre > 0
    assert "mamadou.fall@exemple.sn" not in sortie
    assert "SN91SN0100152000048500000765" not in sortie
    assert "+221 77 555 44 33" not in sortie
    # La structure du CSV survit : le fichier reste exploitable.
    assert sortie.startswith("nom,email,telephone,iban")
    assert sortie.count("\n") == csv_simple.decode().count("\n")


def test_texte_substitution_par_offsets_ne_decale_rien() -> None:
    """Plusieurs entités sur une même ligne : aucune ne doit être décalée."""
    contenu = (
        "a@exemple.sn puis b@exemple.sn puis c@exemple.sn"
    ).encode()
    protege, nombre = proteger(contenu, "text/plain", "t.txt")
    sortie = protege.decode()

    assert nombre == 3
    assert "@exemple.sn" not in sortie
    assert sortie.count("puis") == 2


def test_pdf_le_texte_est_reellement_supprime(pdf_natif: bytes) -> None:
    """Piège n°2 : le texte ne doit plus être extractible après protection."""
    protege, nombre = proteger(pdf_natif, "application/pdf", "doc.pdf")
    assert nombre > 0

    retexte = router.extraire(protege, "application/pdf").texte
    assert "SN91SN0100152000048500000765" not in retexte
    assert "mamadou.fall@exemple.sn" not in retexte


def test_docx_les_valeurs_disparaissent(docx_simple: bytes) -> None:
    protege, nombre = proteger(docx_simple, router.MIME_DOCX, "dossier.docx")
    assert nombre > 0

    retexte = router.extraire(protege, router.MIME_DOCX, "dossier.docx").texte
    assert "mamadou.fall@exemple.sn" not in retexte
    assert "SN91SN0100152000048500000765" not in retexte


@pytest.mark.skipif(not OCR_DISPONIBLE, reason="Tesseract non installé")
def test_image_les_zones_sont_recouvertes(image_jpeg: bytes) -> None:
    import cv2
    import numpy as np

    protege, nombre = proteger(image_jpeg, "image/jpeg", "scan.jpg")
    if nombre == 0:
        pytest.skip("aucune entité reconnue par l'OCR sur cette image de synthèse")

    avant = cv2.imdecode(np.frombuffer(image_jpeg, np.uint8), cv2.IMREAD_COLOR)
    apres = cv2.imdecode(np.frombuffer(protege, np.uint8), cv2.IMREAD_COLOR)
    assert avant.shape == apres.shape
    # Des aplats noirs ont été ajoutés : l'image protégée est plus sombre.
    assert apres.mean() < avant.mean()


def test_seuil_de_niveau_respecte(csv_simple: bytes) -> None:
    """Au seuil `critique`, seuls les IBAN partent ; les courriels restent."""
    protege, _ = proteger(csv_simple, "text/csv", "c.csv", seuil=NiveauSens.critique)
    sortie = protege.decode()
    assert "SN91SN0100152000048500000765" not in sortie
    assert "mamadou.fall@exemple.sn" in sortie


def test_aucune_entite_document_inchange() -> None:
    contenu = b"Rien de personnel ici.\n"
    extraction, _, _ = pipeline.analyser(contenu, "text/plain")
    octets, nombre, _ = mask.appliquer(
        contenu, "text/plain", None, extraction, [], lambda e: "x"
    )
    assert nombre == 0
    assert octets == contenu


def test_pseudonymisation_de_bout_en_bout_est_coherente() -> None:
    """Le même nom, deux fois dans le document, reçoit le même jeton."""
    contenu = b"Client : awa@exemple.sn. Rappel : awa@exemple.sn.\n"
    extraction, entites, _ = pipeline.analyser(contenu, "text/plain")
    octets, _, _ = mask.appliquer(
        contenu,
        "text/plain",
        None,
        extraction,
        entites,
        lambda e: pseudonymize.jeton(e.valeur, e.typeEntite),
    )
    sortie = octets.decode()
    jeton = pseudonymize.jeton("awa@exemple.sn", "EMAIL")
    assert sortie.count(jeton) == 2


def _entite(type_entite: str, debut: int, fin: int, valeur: str) -> Entite:
    return Entite(typeEntite=type_entite, valeur=valeur, debut=debut, fin=fin)
