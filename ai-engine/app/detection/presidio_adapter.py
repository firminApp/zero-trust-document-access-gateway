"""Adaptateur Microsoft Presidio — référence externe de comparaison.

Presidio sert de point de comparaison dans l'évaluation (chapitre III) : même
architecture de principe (reconnaisseurs par motifs + NER + résolution des
chevauchements), implémentation indépendante. Il n'est **pas** requis au
runtime : l'import est local à la classe pour que son absence ne pénalise ni le
démarrage du moteur ni les autres backends.
"""

from __future__ import annotations

import logging

from app.models import Entite, MethodeDetect

logger = logging.getLogger(__name__)

CORRESPONDANCE_PRESIDIO: dict[str, str] = {
    "PERSON": "NOM_PERSONNE",
    "LOCATION": "LOCALITE",
    "NRP": "LOCALITE",
    "ORGANIZATION": "ORGANISATION",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "TELEPHONE",
    "IBAN_CODE": "IBAN",
    "CREDIT_CARD": "CARTE_BANCAIRE",
    "DATE_TIME": "DATE_NAISSANCE",
    "IP_ADDRESS": "ADRESSE_IP",
}


class MoteurPresidio:
    nom = "presidio"

    def __init__(self, seuil: float = 0.50, langue: str = "fr") -> None:
        from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]
        from presidio_analyzer.nlp_engine import (  # type: ignore[import-untyped]
            NlpEngineProvider,
        )

        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": langue, "model_name": "fr_core_news_lg"}],
        }
        moteur_nlp = NlpEngineProvider(nlp_configuration=configuration).create_engine()
        self._analyseur = AnalyzerEngine(
            nlp_engine=moteur_nlp, supported_languages=[langue]
        )
        self._seuil = seuil
        self._langue = langue

    def detecter(self, texte: str) -> list[Entite]:
        resultats = self._analyseur.analyze(text=texte, language=self._langue)
        entites: list[Entite] = []
        for resultat in resultats:
            type_projet = CORRESPONDANCE_PRESIDIO.get(resultat.entity_type)
            if type_projet is None or resultat.score < self._seuil:
                continue
            entites.append(
                Entite(
                    typeEntite=type_projet,
                    valeur=texte[resultat.start : resultat.end],
                    debut=resultat.start,
                    fin=resultat.end,
                    score=round(float(resultat.score), 4),
                    methode=MethodeDetect.ner,
                )
            )
        return entites


def disponible() -> bool:
    """Indique si Presidio est installé, sans le charger."""
    try:
        import importlib.util

        return importlib.util.find_spec("presidio_analyzer") is not None
    except Exception:  # pragma: no cover
        return False
