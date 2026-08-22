"""Campagne d'évaluation de la détection.

    python -m evaluation.run_detection_eval \
        --annotations corpus/data/annotations.jsonl \
        --partition test --backend spacy

Compare, sur le même corpus, les configurations demandées par le mémoire :
règles seules, NER seule, fusion, et Presidio comme référence externe.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.classification import sensitivity
from app.detection import merge, ner, rules
from app.models import Entite
from evaluation.metrics import Empan, evaluer, matrice_confusion
from evaluation.report import ecrire_rapport_confusion, ecrire_rapport_detection

CONFIGURATIONS = ("regles", "ner", "fusion", "presidio")


def charger(annotations: Path, partition: str | None) -> list[dict]:
    documents = []
    with annotations.open(encoding="utf-8") as flux:
        for ligne in flux:
            document = json.loads(ligne)
            if partition and document.get("partition") != partition:
                continue
            documents.append(document)
    return documents


def references_de(document: dict) -> list[Empan]:
    return [
        Empan(
            type_entite=entite["type"],
            debut=entite["debut"],
            fin=entite["fin"],
            niveau=entite["niveau"],
        )
        for entite in document["entites"]
    ]


def predire(texte: str, configuration: str) -> list[Entite]:
    """Produit les prédictions d'une configuration donnée."""
    if configuration == "regles":
        entites = rules.detecter(texte)
    elif configuration == "ner":
        entites = ner.detecter(texte)
    elif configuration == "fusion":
        entites = merge.fusionner(rules.detecter(texte) + ner.detecter(texte))
    elif configuration == "presidio":
        from app.detection.presidio_adapter import MoteurPresidio

        entites = MoteurPresidio().detecter(texte)
    else:
        raise ValueError(f"Configuration inconnue : {configuration}")

    return sensitivity.classer(entites)


def empans_de(entites: list[Entite]) -> list[Empan]:
    return [
        Empan(
            type_entite=e.typeEntite,
            debut=e.debut,
            fin=e.fin,
            niveau=e.niveau.value if hasattr(e.niveau, "value") else str(e.niveau),
        )
        for e in entites
    ]


def executer(
    documents: list[dict], configuration: str, sortie: Path
) -> None:
    references = [references_de(d) for d in documents]
    predictions = [empans_de(predire(d["texte"], configuration)) for d in documents]

    strict = evaluer(references, predictions, strict=True)
    partiel = evaluer(references, predictions, strict=False)

    print(f"\n{'=' * 70}\nConfiguration : {configuration}  ({len(documents)} documents)\n{'=' * 70}")
    ecrire_rapport_detection(strict, partiel, sortie, intitule=f"detection_{configuration}")

    # Les matrices utilisent l'appariement par POSITION, agnostique au type :
    # c'est la seule façon de distinguer « donnée manquée » de « donnée trouvée
    # mais mal étiquetée ». En correspondance stricte, une entité au bon endroit
    # avec de mauvaises frontières serait comptée comme manquée et la confusion
    # de type resterait invisible.
    ecrire_rapport_confusion(
        matrice_confusion(references, predictions, par_niveau=False),
        matrice_confusion(references, predictions, par_niveau=True),
        sortie,
        intitule=f"confusion_{configuration}",
    )


def principal() -> None:
    analyseur = argparse.ArgumentParser(description="Évaluation de la détection")
    analyseur.add_argument(
        "--annotations", type=Path, default=Path("corpus/data/annotations.jsonl")
    )
    analyseur.add_argument("--partition", default="test", help="test | validation | entrainement | tout")
    analyseur.add_argument("--backend", default=None, help="force NER_BACKEND")
    analyseur.add_argument(
        "--configurations",
        default="regles,ner,fusion",
        help=f"parmi {', '.join(CONFIGURATIONS)}",
    )
    analyseur.add_argument("--sortie", type=Path, default=Path("evaluation/resultats"))
    arguments = analyseur.parse_args()

    if arguments.backend:
        os.environ["NER_BACKEND"] = arguments.backend
        from app.config import get_settings

        get_settings.cache_clear()
        ner.reinitialiser_moteur()

    partition = None if arguments.partition == "tout" else arguments.partition
    documents = charger(arguments.annotations, partition)
    if not documents:
        raise SystemExit(
            f"Aucun document dans la partition « {arguments.partition} » de {arguments.annotations}"
        )

    for configuration in arguments.configurations.split(","):
        configuration = configuration.strip()
        if not configuration:
            continue
        try:
            executer(documents, configuration, arguments.sortie)
        except ImportError as erreur:
            print(f"Configuration « {configuration} » ignorée : {erreur}")


if __name__ == "__main__":
    principal()
