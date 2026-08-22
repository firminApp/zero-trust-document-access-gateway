"""Extraction texte brut et CSV, avec détection d'encodage."""

from __future__ import annotations

import logging

from app.extraction.resultat import ResultatExtraction, depuis_texte
from app.models import MethodeExtraction

logger = logging.getLogger(__name__)


# Encodages plausibles pour un export de back-office francophone. Restreindre
# l'espace de recherche évite qu'un fichier latin-1 court soit attribué à un
# encodage d'Europe centrale, qui décode sans erreur mais fausse les accents.
ENCODAGES_CANDIDATS = ("utf_8", "cp1252", "latin_1", "iso8859_15", "cp850", "utf_16")


def decoder(contenu: bytes) -> str:
    """Décode des octets en texte en devinant l'encodage.

    Les exports de back-office ouest-africains arrivent régulièrement en
    latin-1 ; un décodage UTF-8 strict échouerait sur les patronymes accentués.
    """
    # UTF-8 strict d'abord : s'il passe, c'est la bonne réponse, sans heuristique.
    try:
        return contenu.decode("utf-8")
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes

        meilleur = from_bytes(contenu, cp_isolation=list(ENCODAGES_CANDIDATS)).best()
        if meilleur is not None:
            return str(meilleur)
    except Exception as exc:  # pragma: no cover - dépend de la bibliothèque
        logger.debug("charset-normalizer indisponible : %s", exc)

    for encodage in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return contenu.decode(encodage)
        except UnicodeDecodeError:
            continue
    return contenu.decode("utf-8", errors="replace")


def extraire(contenu: bytes) -> ResultatExtraction:
    texte = decoder(contenu)
    return depuis_texte(texte, MethodeExtraction.plain, pages_brutes=[texte])
