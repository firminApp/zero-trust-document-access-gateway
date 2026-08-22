"""Extraction PDF : PyMuPDF en premier, pdfplumber en repli, OCR si scanné."""

from __future__ import annotations

import io
import logging

import fitz  # PyMuPDF
import numpy as np

from app.config import get_settings
from app.extraction.resultat import ResultatExtraction, depuis_texte
from app.models import MethodeExtraction

logger = logging.getLogger(__name__)


def extraire(contenu: bytes) -> ResultatExtraction:
    pages = _pages_pymupdf(contenu)
    if pages is None:
        pages = _pages_pdfplumber(contenu)

    if pages is None:
        logger.warning("Aucun extracteur PDF n'a abouti, bascule OCR")
        return _ocr_pdf(contenu)

    caracteres = sum(len(p.strip()) for p in pages)
    seuil = get_settings().ocr_seuil_caracteres_par_page
    if pages and caracteres / max(1, len(pages)) < seuil:
        # PDF scanné : la couche texte est absente ou résiduelle.
        logger.info(
            "PDF considéré comme scanné (%d car. / %d pages), bascule OCR",
            caracteres,
            len(pages),
        )
        return _ocr_pdf(contenu)

    return depuis_texte("\n\n".join(pages), MethodeExtraction.pdf, pages_brutes=_avec_separateurs(pages))


def _avec_separateurs(pages: list[str]) -> list[str]:
    """Réintroduit le séparateur inter-pages dans le découpage des pages.

    Le texte complet est `"\\n\\n".join(pages)` ; pour que les bornes de page
    correspondent aux offsets réels, chaque page sauf la dernière porte son
    séparateur.
    """
    if not pages:
        return []
    return [p + "\n\n" for p in pages[:-1]] + [pages[-1]]


def _pages_pymupdf(contenu: bytes) -> list[str] | None:
    try:
        with fitz.open(stream=contenu, filetype="pdf") as doc:
            return [page.get_text("text") for page in doc]
    except Exception as exc:
        logger.warning("PyMuPDF a échoué : %s", exc)
        return None


def _pages_pdfplumber(contenu: bytes) -> list[str] | None:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(contenu)) as pdf:
            return [(page.extract_text() or "") for page in pdf.pages]
    except Exception as exc:
        logger.warning("pdfplumber a échoué : %s", exc)
        return None


def _ocr_pdf(contenu: bytes) -> ResultatExtraction:
    """Rend chaque page en image puis lui applique la chaîne OCR."""
    from app.extraction.ocr import (
        cer_estime_depuis_confiance,
        ocr_image_array,
        reprojeter_boites,
    )
    from app.extraction.resultat import BoiteMot

    parametres = get_settings()
    textes: list[str] = []
    boites_brutes: list[BoiteMot] = []
    confiances: list[float] = []
    decalage = 0

    try:
        with fitz.open(stream=contenu, filetype="pdf") as doc:
            for numero, page in enumerate(doc, start=1):
                pixmap = page.get_pixmap(dpi=parametres.ocr_dpi)
                tableau = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n
                )
                if pixmap.n == 4:
                    tableau = tableau[:, :, :3]
                texte, boites, confiance = ocr_image_array(tableau[:, :, ::-1], page=numero)
                for boite in boites:
                    boite.debut += decalage
                    boite.fin += decalage
                boites_brutes.extend(boites)
                confiances.append(confiance)
                bloc = texte + "\n\n"
                textes.append(bloc)
                decalage += len(bloc)
    except Exception as exc:
        logger.error("OCR du PDF impossible : %s", exc)
        return depuis_texte("", MethodeExtraction.ocr, pages_brutes=[])

    confiance_moyenne = float(np.mean(confiances)) if confiances else 0.0
    resultat = depuis_texte(
        "".join(textes),
        MethodeExtraction.ocr,
        pages_brutes=textes,
        cer_estime=cer_estime_depuis_confiance(confiance_moyenne),
    )
    resultat.boites = reprojeter_boites(boites_brutes, resultat)
    return resultat
