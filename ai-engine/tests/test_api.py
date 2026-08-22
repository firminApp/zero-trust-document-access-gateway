"""Contrat d'API du moteur IA (§5.2)."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.main import application


@pytest.fixture()
def client() -> TestClient:
    return TestClient(application)


def encoder(contenu: bytes) -> str:
    return base64.b64encode(contenu).decode()


def test_sante(client: TestClient) -> None:
    reponse = client.get("/sante")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["statut"] == "ok"
    assert "modeleNer" in corps
    assert "versionTesseract" in corps


def test_analyser_texte(client: TestClient, csv_simple: bytes) -> None:
    reponse = client.post(
        "/analyser",
        json={
            "documentId": "doc-1",
            "typeMime": "text/csv",
            "contenuBase64": encoder(csv_simple),
            "nomFichier": "clients.csv",
        },
    )
    assert reponse.status_code == 200
    corps = reponse.json()

    assert corps["texteExtrait"] is True
    assert corps["methodeExtraction"] == "plain"
    assert corps["niveauMax"] == "critique"          # l'IBAN tire le niveau

    types = {e["typeEntite"] for e in corps["entites"]}
    assert {"EMAIL", "IBAN", "TELEPHONE"} <= types

    # Chaque entité porte sa position et son niveau : c'est ce que la
    # passerelle persiste (après hachage de la valeur).
    for entite in corps["entites"]:
        assert entite["debut"] < entite["fin"]
        assert entite["niveau"] in ("faible", "moyen", "eleve", "critique")


def test_analyser_document_sans_dcp(client: TestClient) -> None:
    reponse = client.post(
        "/analyser",
        json={
            "documentId": "doc-2",
            "typeMime": "text/plain",
            "contenuBase64": encoder(b"Compte rendu de reunion technique.\n"),
        },
    )
    corps = reponse.json()
    assert corps["entites"] == []
    assert corps["niveauMax"] is None


def test_analyser_base64_invalide(client: TestClient) -> None:
    reponse = client.post(
        "/analyser",
        json={"documentId": "doc-3", "typeMime": "text/plain", "contenuBase64": "!!!"},
    )
    assert reponse.status_code == 400


def test_proteger_masque(client: TestClient, csv_simple: bytes) -> None:
    reponse = client.post(
        "/proteger",
        json={
            "documentId": "doc-4",
            "typeMime": "text/csv",
            "contenuBase64": encoder(csv_simple),
            "action": "masque",
            "niveauSeuil": "moyen",
        },
    )
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["nbEntitesProtegees"] > 0

    sortie = base64.b64decode(corps["contenuBase64"]).decode()
    assert "mamadou.fall@exemple.sn" not in sortie
    assert "SN91SN0100152000048500000765" not in sortie


def test_proteger_pseudonymise_rend_les_correspondances(
    client: TestClient, csv_simple: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les correspondances sortent chiffrées : la base ne verra aucun clair."""
    monkeypatch.setenv("AES_KEY", "0" * 64)

    reponse = client.post(
        "/proteger",
        json={
            "documentId": "doc-5",
            "typeMime": "text/csv",
            "contenuBase64": encoder(csv_simple),
            "action": "pseudonymise",
            "niveauSeuil": "moyen",
        },
    )
    corps = reponse.json()
    sortie = base64.b64decode(corps["contenuBase64"]).decode()

    assert "mamadou.fall@exemple.sn" not in sortie
    assert corps["correspondances"], "la réversibilité exige des correspondances"
    for lien in corps["correspondances"]:
        assert len(lien["empreinte"]) == 64
        assert "-" in lien["jeton"]
        assert lien["valeurChiffreeBase64"]
        # Aucun clair ne transite dans la correspondance.
        assert "exemple.sn" not in lien["valeurChiffreeBase64"]


def test_proteger_document_sans_dcp(client: TestClient) -> None:
    contenu = b"Note de service : la cantine ferme a 14h.\n"
    reponse = client.post(
        "/proteger",
        json={
            "documentId": "doc-6",
            "typeMime": "text/plain",
            "contenuBase64": encoder(contenu),
            "action": "masque",
            "niveauSeuil": "moyen",
        },
    )
    corps = reponse.json()
    assert corps["nbEntitesProtegees"] == 0
    assert base64.b64decode(corps["contenuBase64"]) == contenu
