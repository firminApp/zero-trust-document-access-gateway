"""Campagne d'évaluation de bout en bout, par condition de dégradation.

    python -m evaluation.run_e2e_eval \
        --index ../corpus/data/scans/index.jsonl \
        --annotations ../corpus/data/annotations.jsonl

C'est la mesure qui **compose** les deux précédentes. `run_ocr_eval` dit
combien de caractères l'OCR abîme ; `run_detection_eval` dit combien d'entités
la détection retrouve dans un texte propre. Ni l'une ni l'autre ne répond à la
question qui décide de la protection réelle : sur un document scanné et
dégradé, quelle proportion des données personnelles le système retrouve-t-il ?

Les deux ne se déduisent pas l'une de l'autre, et c'est tout l'intérêt de la
mesure. Un CER de 0,05 peut sembler excellent tout en détruisant le rappel sur
les types à validateur : un IBAN dont un seul caractère est mal lu échoue au
contrôle mod-97 et disparaît purement et simplement. La précision de 1,000 que
le validateur garantit sur du texte propre devient, sur du texte océrisé, la
cause même de la perte.

Appariement **par valeur** et non par position : les offsets de la vérité
terrain vivent dans le texte d'origine, ceux des prédictions dans le texte
océrisé, et l'OCR insère et supprime des caractères. Voir
`metrics.apparier_par_valeur`.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

from app import pipeline
from app.models import Entite
from evaluation.metrics import TOLERANCE_OCR, Empan, RapportE2E, cer
from evaluation.report import ecrire_rapport_e2e

logger = logging.getLogger(__name__)

def charger_annotations(chemin: Path) -> dict[str, dict]:
    with chemin.open(encoding="utf-8") as flux:
        return {json.loads(ligne)["id"]: json.loads(ligne) for ligne in flux}


def _empans_et_valeurs(entites: list[dict]) -> tuple[list[Empan], list[str]]:
    empans = [
        Empan(e["type"], e["debut"], e["fin"], e["niveau"]) for e in entites
    ]
    return empans, [e["valeur"] for e in entites]


def _predictions(entites: list[Entite]) -> tuple[list[Empan], list[str]]:
    empans = [
        Empan(
            e.typeEntite,
            e.debut,
            e.fin,
            e.niveau.value if hasattr(e.niveau, "value") else str(e.niveau),
        )
        for e in entites
    ]
    return empans, [e.valeur for e in entites]


def executer(
    index: Path,
    annotations: Path,
    sortie: Path,
    limite: int | None,
    partition: str | None,
    tolerance: float,
) -> None:
    if not index.exists():
        raise SystemExit(f"{index} introuvable — lancer d'abord corpus/degrade.py")
    if not annotations.exists():
        raise SystemExit(f"{annotations} introuvable — lancer d'abord corpus/generate.py")

    verite = charger_annotations(annotations)
    entrees = [json.loads(ligne) for ligne in index.open(encoding="utf-8")]

    if partition:
        entrees = [e for e in entrees if e.get("partition") == partition]
    if limite:
        vus: dict[str, int] = defaultdict(int)
        retenues = []
        for entree in entrees:
            if vus[entree["condition"]] < limite:
                vus[entree["condition"]] += 1
                retenues.append(entree)
        entrees = retenues

    if not entrees:
        raise SystemExit("Aucune image à évaluer avec ces filtres")

    rapport = RapportE2E(tolerance=tolerance)

    for numero, entree in enumerate(entrees, start=1):
        document = verite.get(entree["id"])
        if document is None:
            logger.warning("Document %s absent des annotations, ignoré", entree["id"])
            continue

        chemin = index.parent / entree["chemin"]
        if not chemin.exists():
            chemin = Path(entree["chemin"])
        contenu = chemin.read_bytes()

        extraction, entites, _ = pipeline.analyser(contenu, "image/jpeg", chemin.name)

        references, valeurs_reference = _empans_et_valeurs(document["entites"])
        predictions, valeurs_prediction = _predictions(entites)

        rapport.compter(
            entree["condition"],
            references,
            valeurs_reference,
            predictions,
            valeurs_prediction,
            extraction.texte,
            tolerance,
        )
        rapport.cer[entree["condition"]].append(cer(document["texte"], extraction.texte))

        if numero % 10 == 0:
            logger.info("%d / %d images traitées", numero, len(entrees))

    ecrire_rapport_e2e(rapport, sortie)


def principal() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    analyseur = argparse.ArgumentParser(
        description="Évaluation de bout en bout par condition de dégradation"
    )
    analyseur.add_argument("--index", type=Path, default=Path("corpus/data/scans/index.jsonl"))
    analyseur.add_argument(
        "--annotations", type=Path, default=Path("corpus/data/annotations.jsonl")
    )
    analyseur.add_argument("--sortie", type=Path, default=Path("evaluation/resultats"))
    # Par défaut, on évalue TOUT ce que le corpus propose. Un plafond par défaut
    # produirait un chiffre publiable sur un échantillon arbitrairement petit :
    # la première campagne a ainsi manqué la cible de 0,006 sur 18 observations,
    # écart qui s'est révélé être du bruit d'échantillonnage.
    analyseur.add_argument(
        "--limite", type=int, default=0, help="images par condition (0 = toutes)"
    )
    analyseur.add_argument("--partition", default=None, help="test | validation | entrainement")
    analyseur.add_argument(
        "--tolerance",
        type=float,
        default=TOLERANCE_OCR,
        help="part de caractères pouvant différer (0 = correspondance exacte)",
    )
    arguments = analyseur.parse_args()

    executer(
        arguments.index,
        arguments.annotations,
        arguments.sortie,
        arguments.limite,
        arguments.partition,
        arguments.tolerance,
    )


if __name__ == "__main__":
    principal()
