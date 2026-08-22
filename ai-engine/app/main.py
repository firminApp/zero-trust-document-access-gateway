"""Moteur IA — API interne.

Ce service n'est **pas** exposé hors du réseau Docker : aucun port publié dans
`docker-compose.yml`. Il ne détient aucun identifiant de stockage et ne parle à
aucune base : il reçoit des octets, rend une analyse ou un document protégé,
et n'en conserve rien.

`POST /analyser` est le seul endroit du système où des valeurs d'entités
circulent en clair. La passerelle les hache immédiatement à réception.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import pipeline
from app.config import get_settings
from app.detection import ner
from app.extraction.ocr import version_tesseract
from app.models import (
    ActionProtection,
    Entite,
    ReponseAnalyse,
    ReponseProtection,
    ReponseSante,
    RequeteAnalyse,
    RequeteProtection,
)
from app.protection import mask, pseudonymize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("moteur-ia")


@asynccontextmanager
async def cycle_de_vie(_application: FastAPI) -> AsyncIterator[None]:
    """Précharge le backend NER avant d'accepter la première requête.

    Charger le modèle à la volée coûterait plusieurs secondes à la première
    analyse — au détriment de la cible de latence p95 — et ferait converger
    plusieurs requêtes vers la même initialisation.
    """
    parametres = get_settings()
    if parametres.ner_actif:
        moteur = ner.obtenir_moteur()
        logger.info("Backend NER préchargé : %s", moteur.nom)
        if moteur.nom == "aucun":
            logger.error(
                "NER_BACKEND=%s demandé mais indisponible : le service tourne "
                "en mode dégradé (règles seules).",
                parametres.ner_backend,
            )
    yield


application = FastAPI(
    title="Zero-Trust Gateway — moteur IA",
    version="1.0.0",
    description="Extraction, détection, classification et protection des DCP.",
    lifespan=cycle_de_vie,
)
app = application  # alias attendu par uvicorn (`app.main:app`)


class CorrespondanceSortie(BaseModel):
    """Correspondance pseudonyme -> valeur chiffrée, à persister par la passerelle."""

    empreinte: str
    jeton: str
    valeurChiffreeBase64: str | None = None


class ReponseProtectionEtendue(ReponseProtection):
    correspondances: list[CorrespondanceSortie] = []


def _decoder(contenu_base64: str) -> bytes:
    try:
        return base64.b64decode(contenu_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"contenuBase64 invalide : {exc}") from exc


@application.get("/sante", response_model=ReponseSante)
def sante() -> ReponseSante:
    parametres = get_settings()
    modele = ner.obtenir_moteur().nom if parametres.ner_actif else "aucun"
    return ReponseSante(
        statut="ok",
        modeleNer=modele,
        versionTesseract=version_tesseract(),
    )


@application.post("/analyser", response_model=ReponseAnalyse)
def analyser(requete: RequeteAnalyse) -> ReponseAnalyse:
    contenu = _decoder(requete.contenuBase64)
    extraction, entites, niveau = pipeline.analyser(
        contenu, requete.typeMime, requete.nomFichier
    )

    return ReponseAnalyse(
        texteExtrait=bool(extraction.texte.strip()),
        methodeExtraction=extraction.methode,
        cerEstime=extraction.cer_estime,
        entites=entites,
        niveauMax=niveau,
        nbCaracteres=len(extraction.texte),
        nbPages=extraction.nb_pages,
    )


@application.post("/proteger", response_model=ReponseProtectionEtendue)
def proteger(requete: RequeteProtection) -> ReponseProtectionEtendue:
    contenu = _decoder(requete.contenuBase64)
    extraction, entites, _ = pipeline.analyser(
        contenu, requete.typeMime, requete.nomFichier
    )
    a_proteger = pipeline.filtrer_par_seuil(entites, requete.niveauSeuil)

    correspondances: list[CorrespondanceSortie] = []

    if requete.action == ActionProtection.masque:

        def remplacer(entite: Entite) -> str:
            return mask.masquer_valeur(entite.valeur, entite.typeEntite)

    else:
        deja_vues: set[str] = set()

        def remplacer(entite: Entite) -> str:
            lien = pseudonymize.correspondance(entite.valeur, entite.typeEntite)
            if lien.jeton not in deja_vues:
                deja_vues.add(lien.jeton)
                correspondances.append(
                    CorrespondanceSortie(
                        empreinte=lien.empreinte,
                        jeton=lien.jeton,
                        valeurChiffreeBase64=lien.valeurChiffreeBase64,
                    )
                )
            return lien.jeton

    octets, nombre, type_sortie = mask.appliquer(
        contenu,
        requete.typeMime,
        requete.nomFichier,
        extraction,
        a_proteger,
        remplacer,
    )

    logger.info(
        "Protection %s du document %s : %d/%d entités traitées",
        requete.action.value,
        requete.documentId,
        nombre,
        len(a_proteger),
    )

    return ReponseProtectionEtendue(
        contenuBase64=base64.b64encode(octets).decode(),
        nbEntitesProtegees=nombre,
        typeMimeSortie=type_sortie,
        correspondances=correspondances,
    )
