"""Extraction multi-format (critère d'acceptation M3).

« Un PDF natif, un PDF scanné, un DOCX, un CSV et un JPG produisent tous du
texte. » Les assertions sur l'OCR restent volontairement souples : le CER
exact se mesure dans `evaluation/run_ocr_eval.py`, pas ici.
"""

from __future__ import annotations

import shutil

import pytest

from app.extraction import router
from app.models import MethodeExtraction

OCR_DISPONIBLE = shutil.which("tesseract") is not None
sans_ocr = pytest.mark.skipif(not OCR_DISPONIBLE, reason="Tesseract non installé")


def test_pdf_natif(pdf_natif: bytes) -> None:
    resultat = router.extraire(pdf_natif, "application/pdf")
    assert resultat.methode == MethodeExtraction.pdf
    assert "FALL" in resultat.texte
    assert "SN91SN0100152000048500000765" in resultat.texte


@sans_ocr
def test_pdf_scanne_bascule_vers_ocr(pdf_scanne: bytes) -> None:
    resultat = router.extraire(pdf_scanne, "application/pdf")
    assert resultat.methode == MethodeExtraction.ocr
    assert len(resultat.texte.strip()) > 20


def test_docx(docx_simple: bytes) -> None:
    resultat = router.extraire(docx_simple, router.MIME_DOCX, "dossier.docx")
    assert resultat.methode == MethodeExtraction.docx
    assert "FALL" in resultat.texte
    assert "GZ-889201" in resultat.texte          # en-tête
    assert "awa.diouf@exemple.sn" in resultat.texte  # tableau


def test_csv(csv_simple: bytes) -> None:
    resultat = router.extraire(csv_simple, "text/csv", "clients.csv")
    assert resultat.methode == MethodeExtraction.plain
    assert "mamadou.fall@exemple.sn" in resultat.texte


def test_csv_latin1_est_decode(csv_latin1: bytes) -> None:
    resultat = router.extraire(csv_latin1, "text/csv", "clients.csv")
    assert "Thérèse" in resultat.texte or "Therese" in resultat.texte


@sans_ocr
def test_jpeg(image_jpeg: bytes) -> None:
    resultat = router.extraire(image_jpeg, "image/jpeg", "scan.jpg")
    assert resultat.methode == MethodeExtraction.ocr
    assert len(resultat.texte.strip()) > 20
    assert resultat.boites, "l'OCR doit produire des boîtes englobantes"


def test_document_vide() -> None:
    resultat = router.extraire(b"", "text/plain")
    assert resultat.texte == ""
    assert resultat.methode == MethodeExtraction.aucune


# --- Aiguillage par signature ------------------------------------------------


@pytest.mark.parametrize(
    "octets,annonce,attendu",
    [
        (b"%PDF-1.7\n", "application/octet-stream", router.MIME_PDF),
        (b"\xff\xd8\xff\xe0", None, "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "application/octet-stream", "image/png"),
        (b"nom,ville\n", "text/csv", "text/csv"),
    ],
)
def test_la_signature_prime_sur_le_type_annonce(
    octets: bytes, annonce: str | None, attendu: str
) -> None:
    """Une source qui annonce mal son contenu ne doit pas dérouter l'extraction."""
    assert router.deviner_type(octets, annonce) == attendu


def test_pdf_annonce_comme_texte_est_bien_traite(pdf_natif: bytes) -> None:
    resultat = router.extraire(pdf_natif, "text/plain", "document.txt")
    assert resultat.methode == MethodeExtraction.pdf
