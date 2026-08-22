"""Campagne d'évaluation de l'OCR, par condition de dégradation.

    python -m evaluation.run_ocr_eval --index corpus/data/scans/index.jsonl

Le CER est mesuré contre la vérité terrain du corpus synthétique — le texte
qui a servi à produire l'image. Contrairement au `cerEstime` renvoyé par
`/analyser` (dérivé de la confiance Tesseract), c'est ici une vraie mesure.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app.extraction import ocr
from evaluation.metrics import cer
from evaluation.report import ecrire_rapport_ocr


def executer(index: Path, sortie: Path, limite: int | None) -> None:
    if not index.exists():
        raise SystemExit(f"{index} introuvable — lancer d'abord corpus/degrade.py")

    entrees = [json.loads(ligne) for ligne in index.open(encoding="utf-8")]
    if limite:
        par_condition: dict[str, int] = defaultdict(int)
        retenues = []
        for entree in entrees:
            if par_condition[entree["condition"]] < limite:
                par_condition[entree["condition"]] += 1
                retenues.append(entree)
        entrees = retenues

    mesures: dict[str, list[float]] = defaultdict(list)

    for entree in entrees:
        chemin = index.parent / entree["chemin"]
        if not chemin.exists():
            chemin = Path(entree["chemin"])  # index produit par une version antérieure
        contenu = chemin.read_bytes()
        resultat = ocr.extraire(contenu)
        mesures[entree["condition"]].append(cer(entree["texte"], resultat.texte))

    lignes = []
    for condition in ("reference", "bruit", "flou", "rotation", "jpeg40"):
        valeurs = mesures.get(condition)
        if not valeurs:
            continue
        ordonnees = sorted(valeurs)
        p90 = ordonnees[min(len(ordonnees) - 1, int(0.9 * len(ordonnees)))]
        lignes.append(
            [
                condition,
                str(len(valeurs)),
                f"{statistics.fmean(valeurs):.4f}",
                f"{statistics.median(valeurs):.4f}",
                f"{p90:.4f}",
            ]
        )

    ecrire_rapport_ocr(lignes, sortie)


def principal() -> None:
    analyseur = argparse.ArgumentParser(description="Évaluation de l'OCR")
    analyseur.add_argument("--index", type=Path, default=Path("corpus/data/scans/index.jsonl"))
    analyseur.add_argument("--sortie", type=Path, default=Path("evaluation/resultats"))
    analyseur.add_argument("--limite", type=int, default=20, help="documents par condition")
    arguments = analyseur.parse_args()

    executer(arguments.index, arguments.sortie, arguments.limite)


if __name__ == "__main__":
    principal()
