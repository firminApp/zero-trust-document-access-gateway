"""Pseudonymisation déterministe et réversible.

`Jean Dupont` -> `PERS-4F2A`. Deux propriétés attendues :

  * **déterminisme** — la même valeur donne toujours le même jeton, sinon un
    analyste ne peut plus recouper deux documents parlant de la même personne,
    ce qui est précisément l'intérêt de pseudonymiser plutôt que de masquer ;
  * **réversibilité contrôlée** — la valeur d'origine repart chiffrée
    (AES-GCM), la passerelle la range dans `pseudonyme.valeur_chiffree`. Sans
    la clé, la table ne rend rien.

Le jeton dérive d'une empreinte **salée** : sans le sel serveur, une attaque
par dictionnaire sur un espace de noms restreint retrouverait les valeurs.
"""

from __future__ import annotations

import base64
import hashlib
import unicodedata
from dataclasses import dataclass

from app.config import get_settings
from app.protection import crypt

PREFIXES: dict[str, str] = {
    "NOM_PERSONNE": "PERS",
    "PRENOM": "PERS",
    "EMAIL": "MAIL",
    "TELEPHONE": "TEL",
    "ADRESSE_POSTALE": "ADR",
    "LOCALITE": "LIEU",
    "ORGANISATION": "ORG",
    "IBAN": "IBAN",
    "CARTE_BANCAIRE": "CB",
    "NUM_PIECE_IDENTITE": "PIECE",
    "DATE_NAISSANCE": "DATE",
    "NUM_CLIENT": "CLI",
    "PLAQUE_IMMAT": "PLAQ",
}
PREFIXE_DEFAUT = "DCP"
LONGUEUR_SUFFIXE = 4


@dataclass
class Correspondance:
    """Ligne destinée à la table `pseudonyme`. Aucune valeur en clair."""

    empreinte: str
    jeton: str
    valeurChiffreeBase64: str | None


def normaliser_valeur(valeur: str) -> str:
    """Forme canonique d'une valeur avant hachage.

    « Jean DUPONT », « jean dupont » et « Jean  Dupont » doivent produire le
    même jeton, sans quoi le déterminisme ne tient pas sur des documents
    saisis par des humains.
    """
    sans_accents = unicodedata.normalize("NFKD", valeur)
    sans_accents = "".join(c for c in sans_accents if not unicodedata.combining(c))
    return " ".join(sans_accents.lower().split())


def empreinte(valeur: str, sel: str | None = None) -> str:
    """SHA-256(valeur canonique || sel serveur), en hexadécimal."""
    graine = sel if sel is not None else get_settings().hash_salt
    canonique = normaliser_valeur(valeur)
    return hashlib.sha256(f"{canonique}{graine}".encode()).hexdigest()


def jeton(valeur: str, type_entite: str, sel: str | None = None) -> str:
    """Jeton stable de la forme `PERS-4F2A`."""
    prefixe = PREFIXES.get(type_entite.upper(), PREFIXE_DEFAUT)
    suffixe = empreinte(valeur, sel)[:LONGUEUR_SUFFIXE].upper()
    return f"{prefixe}-{suffixe}"


def correspondance(valeur: str, type_entite: str, sel: str | None = None) -> Correspondance:
    """Construit la ligne de correspondance à persister côté passerelle.

    Si `AES_KEY` n'est pas configurée, la pseudonymisation reste déterministe
    mais devient irréversible : `valeurChiffreeBase64` vaut `None` et la
    passerelle n'enregistre pas la correspondance.
    """
    chiffree: str | None = None
    if crypt.chiffrement_disponible():
        chiffree = base64.b64encode(crypt.chiffrer(valeur.encode("utf-8"))).decode()

    return Correspondance(
        empreinte=empreinte(valeur, sel),
        jeton=jeton(valeur, type_entite, sel),
        valeurChiffreeBase64=chiffree,
    )
