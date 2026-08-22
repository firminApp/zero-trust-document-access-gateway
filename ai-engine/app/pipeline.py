"""Chaîne d'analyse : extraction -> détection -> fusion -> classification.

Partagée par `/analyser` et `/proteger` : protéger un document suppose de
savoir ce qu'il contient, et cette connaissance doit être obtenue exactement
de la même façon dans les deux cas. Une divergence entre les deux chemins
signifierait qu'on masque autre chose que ce qu'on a classé.
"""

from __future__ import annotations

import logging
import time

from app.classification import sensitivity
from app.detection import merge, ner, rules
from app.extraction import router
from app.extraction.resultat import ResultatExtraction
from app.models import Entite, MethodeExtraction, NiveauSens

logger = logging.getLogger(__name__)


def analyser(
    contenu: bytes, type_mime: str | None = None, nom: str | None = None
) -> tuple[ResultatExtraction, list[Entite], NiveauSens | None]:
    """Analyse complète d'un document. Retourne (extraction, entités, niveau max)."""
    depart = time.perf_counter()

    extraction = router.extraire(contenu, type_mime, nom)
    texte = extraction.texte

    # Les règles ont besoin de savoir si le texte vient de l'OCR : elles y
    # tolèrent les jetons disloqués et les sommes de contrôle en échec, ce
    # qu'elles n'ont aucune raison de faire sur du texte propre.
    issu_ocr = extraction.methode == MethodeExtraction.ocr

    entites: list[Entite] = []
    if texte.strip():
        entites.extend(rules.detecter(texte, ocr=issu_ocr))
        entites.extend(ner.detecter(texte))
        entites = merge.fusionner(entites)
        entites = sensitivity.classer(entites)
        for entite in entites:
            entite.page = extraction.page_de(entite.debut)

    niveau = sensitivity.niveau_maximum(entites)

    logger.info(
        "Analyse : %d caractères (%s), %d entités, niveau=%s, %.0f ms",
        len(texte),
        extraction.methode.value,
        len(entites),
        niveau,
        (time.perf_counter() - depart) * 1000,
    )
    return extraction, entites, niveau


def filtrer_par_seuil(entites: list[Entite], seuil: NiveauSens) -> list[Entite]:
    """Ne conserve que les entités de niveau supérieur ou égal au seuil."""
    return [e for e in entites if sensitivity.au_moins(e.niveau, seuil)]
