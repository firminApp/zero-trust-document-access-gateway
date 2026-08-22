"""Aiguillage de l'extraction par type MIME.

Le type MIME annoncé par la source n'est pas fiable (un `application/octet-stream`
peut être un PDF). On confronte donc l'annonce à la signature des premiers
octets, et la signature l'emporte.
"""

from __future__ import annotations

import logging

from app.extraction import docx as extracteur_docx
from app.extraction import ocr as extracteur_ocr
from app.extraction import pdf as extracteur_pdf
from app.extraction import plain as extracteur_plain
from app.extraction.resultat import ResultatExtraction, depuis_texte
from app.models import MethodeExtraction

logger = logging.getLogger(__name__)

MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIMES_TEXTE = {"text/plain", "text/csv", "application/json", "text/html", "text/markdown"}
MIMES_IMAGE = {"image/jpeg", "image/jpg", "image/png", "image/tiff", "image/bmp", "image/webp"}


def deviner_type(contenu: bytes, type_mime: str | None, nom: str | None = None) -> str:
    """Détermine le type MIME effectif à partir de la signature du fichier."""
    entete = contenu[:8]

    if entete.startswith(b"%PDF"):
        return MIME_PDF
    if entete.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if entete.startswith(b"\x89PNG"):
        return "image/png"
    if entete[:2] in (b"II", b"MM") and contenu[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if entete.startswith(b"PK\x03\x04"):
        # Conteneur ZIP : DOCX si l'annonce ou l'extension le disent.
        if (type_mime == MIME_DOCX) or (nom or "").lower().endswith(".docx"):
            return MIME_DOCX
        if b"word/document.xml" in contenu[:8192]:
            return MIME_DOCX
        return MIME_DOCX  # seul format Office pris en charge par le prototype

    if type_mime:
        normalise = type_mime.split(";")[0].strip().lower()
        if normalise in MIMES_IMAGE or normalise in MIMES_TEXTE:
            return normalise
        if normalise in (MIME_PDF, MIME_DOCX):
            return normalise

    nom_bas = (nom or "").lower()
    for extension, mime in (
        (".pdf", MIME_PDF),
        (".docx", MIME_DOCX),
        (".csv", "text/csv"),
        (".txt", "text/plain"),
        (".json", "application/json"),
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".png", "image/png"),
    ):
        if nom_bas.endswith(extension):
            return mime

    return "text/plain"


def extraire(
    contenu: bytes, type_mime: str | None = None, nom: str | None = None
) -> ResultatExtraction:
    """Extrait le texte d'un document quel que soit son format."""
    if not contenu:
        return depuis_texte("", MethodeExtraction.aucune, pages_brutes=[])

    effectif = deviner_type(contenu, type_mime, nom)
    logger.debug("Extraction : type annoncé=%s, effectif=%s", type_mime, effectif)

    if effectif == MIME_PDF:
        return extracteur_pdf.extraire(contenu)
    if effectif == MIME_DOCX:
        return extracteur_docx.extraire(contenu)
    if effectif in MIMES_IMAGE:
        return extracteur_ocr.extraire(contenu)
    return extracteur_plain.extraire(contenu)
