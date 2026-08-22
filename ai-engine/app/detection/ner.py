"""Reconnaissance d'entités nommées — deux backends derrière une interface.

L'arbitrage coût/qualité entre spaCy et CamemBERT est un résultat attendu du
mémoire : les deux moteurs sont donc interchangeables par variable
d'environnement (`NER_BACKEND`), sans aucun changement dans le code appelant.

Seuil de confiance délibérément bas (0,50) : la métrique de décision est le F2,
un faux négatif coûte plus cher qu'un faux positif.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Protocol

from app.config import get_settings
from app.extraction.normalize import segmenter
from app.models import Entite, MethodeDetect

logger = logging.getLogger(__name__)

# Correspondance des étiquettes des modèles vers la taxonomie du projet.
CORRESPONDANCE_ETIQUETTES: dict[str, str] = {
    "PER": "NOM_PERSONNE",
    "PERSON": "NOM_PERSONNE",
    "PERS": "NOM_PERSONNE",
    "LOC": "LOCALITE",
    "GPE": "LOCALITE",
    "ORG": "ORGANISATION",
    "FAC": "LOCALITE",
}


class MoteurNER(Protocol):
    """Interface commune aux backends de reconnaissance d'entités."""

    nom: str

    def detecter(self, texte: str) -> list[Entite]: ...


def recadrer(texte: str, debut: int, fin: int) -> tuple[int, int, str]:
    """Resserre un empan sur sa valeur utile et rend la sous-chaîne exacte.

    Les tokenizers SentencePiece — donc CamemBERT — marquent le début de mot
    par « ▁ » et rendent un offset qui **inclut l'espace précédent** :
    `' Awa Diouf'` au lieu de `'Awa Diouf'`. L'empan est alors décalé d'un
    caractère, et deux conséquences en découlent :

      * en évaluation, aucune correspondance stricte de frontière n'aboutit,
        ce qui fait chuter le rappel mesuré à zéro alors que le modèle a bien
        trouvé l'entité ;
      * en production, le masquage efface l'espace et laisse le dernier
        caractère de la donnée visible.

    On recadre donc systématiquement, et on prend la valeur **dans le texte
    source** plutôt que celle rendue par le modèle : c'est la seule qui soit
    garantie cohérente avec les offsets.
    """
    debut = max(0, min(debut, len(texte)))
    fin = max(debut, min(fin, len(texte)))

    while debut < fin and texte[debut].isspace():
        debut += 1
    while fin > debut and texte[fin - 1].isspace():
        fin -= 1

    return debut, fin, texte[debut:fin]


# --- Adresses postales -------------------------------------------------------

MOTS_VOIE = (
    "rue", "avenue", "av", "boulevard", "bd", "impasse", "allee", "allée",
    "route", "rte", "place", "quartier", "cite", "cité", "villa", "lot",
    "carrefour", "sicap", "hlm", "grand yoff", "medina", "médina",
    "zone", "parcelle", "immeuble", "residence", "résidence", "bp", "b.p",
)

# La classe de fin exclut délibérément `\n` : avec `\s`, l'empan déborderait sur
# la ligne suivante (« ...Parakou\nTéléphone »), et le masquage effacerait des
# libellés de formulaire tout en manquant la fin réelle de l'adresse.
MOTIF_ADRESSE = re.compile(
    r"(?:(?:n[°o]\s*)?\d{1,4}[, \t]+)?"
    r"\b(?:" + "|".join(MOTS_VOIE) + r")\b"
    r"[ \t.,'’\-\w]{3,60}",
    flags=re.IGNORECASE,
)

MOTIF_CODE_POSTAL = re.compile(r"\b\d{5}\b[ \t]+[A-ZÉÈÀÂÎÔÛ][\w\-']+")


def detecter_adresses(texte: str) -> list[Entite]:
    """Repère les adresses postales par indices de voie.

    Aucun modèle NER français grand public ne produit une étiquette
    « adresse » : on la reconstruit par motif lexical. Le résultat est rattaché
    à la famille NER car il relève de la même logique contextuelle.
    """
    entites: list[Entite] = []
    vus: set[tuple[int, int]] = set()

    for motif, score in ((MOTIF_ADRESSE, 0.65), (MOTIF_CODE_POSTAL, 0.60)):
        for correspondance in motif.finditer(texte):
            valeur = correspondance.group(0).strip(" ,;.")
            if len(valeur) < 8:
                continue
            debut = correspondance.start()
            fin = debut + len(valeur)
            if (debut, fin) in vus:
                continue
            vus.add((debut, fin))
            entites.append(
                Entite(
                    typeEntite="ADRESSE_POSTALE",
                    valeur=valeur,
                    debut=debut,
                    fin=fin,
                    score=score,
                    methode=MethodeDetect.ner,
                )
            )
    return entites


# --- Backend spaCy -----------------------------------------------------------


class MoteurSpacy:
    nom = "spacy"

    def __init__(self, modele: str) -> None:
        import spacy

        try:
            self._nlp = spacy.load(modele, exclude=["lemmatizer", "textcat"])
        except OSError:
            logger.warning(
                "Modèle spaCy '%s' absent, repli sur 'fr_core_news_sm'", modele
            )
            self._nlp = spacy.load("fr_core_news_sm", exclude=["lemmatizer", "textcat"])
        self.nom = f"spacy:{modele}"

    def detecter(self, texte: str) -> list[Entite]:
        entites: list[Entite] = []
        for debut_segment, fin_segment in _segments(texte):
            fragment = texte[debut_segment:fin_segment]
            document = self._nlp(fragment)
            for entite in document.ents:
                type_projet = CORRESPONDANCE_ETIQUETTES.get(entite.label_)
                if type_projet is None:
                    continue
                debut, fin, valeur = recadrer(
                    texte,
                    debut_segment + entite.start_char,
                    debut_segment + entite.end_char,
                )
                if not valeur:
                    continue
                entites.append(
                    Entite(
                        typeEntite=type_projet,
                        valeur=valeur,
                        debut=debut,
                        fin=fin,
                        # spaCy ne fournit pas de probabilité par entité avec le
                        # pipeline standard : on affecte un score constant au-dessus
                        # du seuil, la confiance discriminante venant de CamemBERT.
                        score=0.85,
                        methode=MethodeDetect.ner,
                    )
                )
        return entites


# --- Backend CamemBERT -------------------------------------------------------


class MoteurCamembert:
    nom = "camembert"

    def __init__(self, modele: str, seuil: float) -> None:
        from transformers import (  # type: ignore[import-untyped]
            AutoModelForTokenClassification,
            AutoTokenizer,
            pipeline,
        )

        tokenizer = AutoTokenizer.from_pretrained(modele)
        reseau = AutoModelForTokenClassification.from_pretrained(modele)
        self._pipeline = pipeline(
            "token-classification",
            model=reseau,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
        )
        self._seuil = seuil
        self.nom = f"camembert:{modele}"

    def detecter(self, texte: str) -> list[Entite]:
        entites: list[Entite] = []
        for debut_segment, fin_segment in _segments(texte):
            fragment = texte[debut_segment:fin_segment]
            if not fragment.strip():
                continue
            for brute in self._pipeline(fragment):
                etiquette = str(brute.get("entity_group", "")).upper()
                type_projet = CORRESPONDANCE_ETIQUETTES.get(etiquette)
                score = float(brute.get("score", 0.0))
                if type_projet is None or score < self._seuil:
                    continue
                debut, fin, valeur = recadrer(
                    texte,
                    debut_segment + int(brute["start"]),
                    debut_segment + int(brute["end"]),
                )
                if not valeur:
                    continue
                entites.append(
                    Entite(
                        typeEntite=type_projet,
                        valeur=valeur,
                        debut=debut,
                        fin=fin,
                        score=round(score, 4),
                        methode=MethodeDetect.ner,
                    )
                )
        return entites


# --- Backend neutre ----------------------------------------------------------


class MoteurAucun:
    """Backend de repli : aucune NER, uniquement les adresses par motif.

    Utilisé lorsque `NER_BACKEND=aucun` ou lorsqu'aucun modèle n'a pu être
    chargé. Le système reste fonctionnel — dégradé sur le rappel, pas cassé.
    """

    nom = "aucun"

    def detecter(self, texte: str) -> list[Entite]:  # noqa: ARG002
        return []


_moteur: MoteurNER | None = None

# Le chargement du backend doit être sérialisé. Sans verrou, deux requêtes
# concurrentes entrent ensemble dans l'initialisation ; l'import paresseux de
# `transformers` n'est pas réentrant et l'une des deux échoue avec un
# « cannot import name ... ». Comme les deux affectent `_moteur`, celle qui a
# échoué peut gagner et le service reste durablement sans NER — un système
# silencieusement dégradé, donc un rappel effondré sans aucune alerte.
_verrou = threading.Lock()


def obtenir_moteur() -> MoteurNER:
    """Instancie (une fois) le backend désigné par `NER_BACKEND`."""
    global _moteur
    if _moteur is not None:
        return _moteur

    with _verrou:
        if _moteur is not None:
            return _moteur
        return _construire_moteur()


def _construire_moteur() -> MoteurNER:
    global _moteur
    parametres = get_settings()
    backend = parametres.ner_backend

    try:
        if backend == "camembert":
            _moteur = MoteurCamembert(parametres.camembert_model, parametres.ner_threshold)
        elif backend == "spacy":
            _moteur = MoteurSpacy(parametres.spacy_model)
        elif backend == "presidio":
            from app.detection.presidio_adapter import MoteurPresidio

            _moteur = MoteurPresidio(parametres.ner_threshold)
        else:
            _moteur = MoteurAucun()
    except Exception as exc:
        logger.error(
            "Backend NER '%s' indisponible (%s) — repli sans NER. "
            "Le rappel sur les entités contextuelles sera dégradé.",
            backend,
            exc,
        )
        _moteur = MoteurAucun()

    logger.info("Backend NER actif : %s", _moteur.nom)
    return _moteur


def reinitialiser_moteur() -> None:
    """Vide le cache du backend — utilisé par les tests."""
    global _moteur
    with _verrou:
        _moteur = None


def detecter(texte: str) -> list[Entite]:
    """Détection NER complète : modèle + adresses postales."""
    if not texte.strip():
        return []
    parametres = get_settings()
    entites = detecter_adresses(texte)
    if parametres.ner_actif:
        entites.extend(obtenir_moteur().detecter(texte))
    return [e for e in entites if e.score >= parametres.ner_threshold]


def _segments(texte: str) -> list[tuple[int, int]]:
    parametres = get_settings()
    return segmenter(
        texte, parametres.fenetre_sous_mots, parametres.recouvrement_sous_mots
    )
