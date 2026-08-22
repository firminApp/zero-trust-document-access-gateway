"""Chiffrement AES-256-GCM.

Deux usages :
  * réversibilité de la pseudonymisation — la valeur d'origine est chiffrée
    avant de sortir du moteur, si bien que la table `pseudonyme` de la base
    ne contient jamais de clair (invariant §2) ;
  * [M6.5, optionnel] chiffrement au repos des documents.

La clé vit dans `AES_KEY` (variable d'environnement ou gestionnaire de
secrets), jamais en base : une base compromise sans la clé ne rend rien.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TAILLE_NONCE = 12


class CleAbsente(RuntimeError):
    """Levée quand une opération de chiffrement est demandée sans clé."""


def _lire_cle(cle_brute: str | None = None) -> bytes | None:
    """Décode la clé depuis l'hexadécimal ou le base64. 32 octets attendus."""
    valeur = cle_brute if cle_brute is not None else os.environ.get("AES_KEY", "")
    valeur = (valeur or "").strip()
    if not valeur:
        return None

    for decodeur in (binascii.unhexlify, base64.b64decode):
        try:
            octets = decodeur(valeur)
        except Exception:
            continue
        if len(octets) in (16, 24, 32):
            return octets

    octets = valeur.encode("utf-8")
    if len(octets) in (16, 24, 32):
        return octets
    raise CleAbsente(
        "AES_KEY doit décoder vers 16, 24 ou 32 octets (hex, base64 ou brut)"
    )


def chiffrement_disponible(cle_brute: str | None = None) -> bool:
    try:
        return _lire_cle(cle_brute) is not None
    except CleAbsente:
        return False


def chiffrer(clair: bytes, cle_brute: str | None = None) -> bytes:
    """Chiffre en AES-GCM. Le nonce est préfixé au cryptogramme."""
    cle = _lire_cle(cle_brute)
    if cle is None:
        raise CleAbsente("AES_KEY n'est pas configurée")
    nonce = os.urandom(TAILLE_NONCE)
    return nonce + AESGCM(cle).encrypt(nonce, clair, None)


def dechiffrer(cryptogramme: bytes, cle_brute: str | None = None) -> bytes:
    """Déchiffre un cryptogramme produit par `chiffrer`."""
    cle = _lire_cle(cle_brute)
    if cle is None:
        raise CleAbsente("AES_KEY n'est pas configurée")
    if len(cryptogramme) <= TAILLE_NONCE:
        raise ValueError("cryptogramme tronqué")
    nonce, corps = cryptogramme[:TAILLE_NONCE], cryptogramme[TAILLE_NONCE:]
    return AESGCM(cle).decrypt(nonce, corps, None)


def generer_cle() -> str:
    """Génère une clé AES-256 encodée en hexadécimal, pour `.env`."""
    return os.urandom(32).hex()
