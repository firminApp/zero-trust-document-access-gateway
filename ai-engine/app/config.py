"""Configuration du moteur IA, lue depuis l'environnement.

Le moteur ne reçoit jamais d'identifiants de stockage : il travaille sur des
octets qui lui sont transmis par la passerelle. Les seules valeurs sensibles
ici sont le sel de hachage et, pour M6.5, la clé AES.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    """Paramètres d'exécution du moteur IA."""

    # --- Détection ---------------------------------------------------------
    ner_backend: str = "spacy"          # spacy | camembert | presidio | aucun
    ner_threshold: float = 0.50
    spacy_model: str = "fr_core_news_lg"
    camembert_model: str = "Jean-Baptiste/camembert-ner"

    # --- Extraction / OCR --------------------------------------------------
    ocr_lang: str = "fra"
    # En dessous de ce nombre de caractères par page, un PDF est considéré
    # comme scanné et bascule vers l'OCR.
    ocr_seuil_caracteres_par_page: int = 100
    ocr_dpi: int = 300

    # --- Segmentation ------------------------------------------------------
    fenetre_sous_mots: int = 512
    recouvrement_sous_mots: int = 64

    # --- Protection --------------------------------------------------------
    hash_salt: str = "change-me"
    aes_key: str = ""                   # M6.5, optionnel (base64 ou hex 32 octets)

    @property
    def ner_actif(self) -> bool:
        return self.ner_backend not in ("", "aucun", "none")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    def _f(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except ValueError:
            return default

    def _i(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, default))
        except ValueError:
            return default

    return Settings(
        ner_backend=os.environ.get("NER_BACKEND", "spacy").strip().lower(),
        ner_threshold=_f("NER_THRESHOLD", 0.50),
        spacy_model=os.environ.get("SPACY_MODEL", "fr_core_news_lg"),
        camembert_model=os.environ.get("CAMEMBERT_MODEL", "Jean-Baptiste/camembert-ner"),
        ocr_lang=os.environ.get("OCR_LANG", "fra"),
        ocr_seuil_caracteres_par_page=_i("OCR_SEUIL_CARACTERES_PAR_PAGE", 100),
        ocr_dpi=_i("OCR_DPI", 300),
        fenetre_sous_mots=_i("FENETRE_SOUS_MOTS", 512),
        recouvrement_sous_mots=_i("RECOUVREMENT_SOUS_MOTS", 64),
        hash_salt=os.environ.get("HASH_SALT", "change-me"),
        aes_key=os.environ.get("AES_KEY", ""),
    )
