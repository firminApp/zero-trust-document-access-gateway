"""Diagnostic : d'où vient l'écart de CER sous bruit entre les deux campagnes ?

`run_ocr_eval` mesure 0,151 sous bruit ; `run_e2e_eval` mesure 0,428 sur les
mêmes images, avec la même fonction `cer()` et la même vérité terrain. Les
quatre autres conditions concordent. Ce script isole la cause en mesurant le
CER de trois façons, sur exactement le même sous-ensemble d'images :

    A1, A2  `ocr.extraire` seul, avant tout import de `app.pipeline`
            (donc avant que torch et transformers soient chargés).
            Deux passes : A1 == A2 vérifie que la chaîne est déterministe.
    B       `ocr.extraire` seul, APRÈS l'import du pipeline.
            Même code, mêmes images ; seul le contenu du processus a changé.
    C       `pipeline.analyser`, exactement comme la campagne de bout en bout.

Lecture des résultats :

    A1 != A2          la chaîne OCR n'est pas déterministe. Chercher du côté
                      de la décision de redressement (`_redresser`), qui a un
                      pire cas catastrophique documenté à CER 5,9.
    A == B == C       l'écart ne vient pas du chemin d'exécution : comparer
                      alors les variables d'environnement des deux campagnes
                      (OCR_LANG, TESSDATA_PREFIX) et la version de Tesseract.
    A != B            l'import de torch / transformers change le résultat de
                      la chaîne OpenCV. C'est le cas le plus intéressant :
                      les deux bibliothèques lient OpenMP, et le nombre de
                      fils d'OpenCV n'est plus le même après l'import. Le
                      correctif est alors de figer explicitement
                      `cv2.setNumThreads(1)` dans `app/extraction/ocr.py`.

Usage :

    cd ai-engine
    PYTHONPATH=. .venv/bin/python -m evaluation.diagnostic_cer
    PYTHONPATH=. .venv/bin/python -m evaluation.diagnostic_cer --par-condition 0

Le plafond par défaut de 20 images par condition est ici légitime : on compare
trois mesures sur LE MÊME sous-ensemble, on ne publie pas un CER. Passer
`--par-condition 0` pour traiter les soixante documents.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path

CONDITIONS = ("reference", "bruit", "flou", "rotation", "jpeg40")


def charger(index: Path, par_condition: int) -> list[dict]:
    entrees = [json.loads(ligne) for ligne in index.open(encoding="utf-8")]
    if not par_condition:
        return entrees
    vus: dict[str, int] = defaultdict(int)
    retenues = []
    for entree in entrees:
        if vus[entree["condition"]] < par_condition:
            vus[entree["condition"]] += 1
            retenues.append(entree)
    return retenues


def _chemin(index: Path, entree: dict) -> Path:
    chemin = index.parent / entree["chemin"]
    return chemin if chemin.exists() else Path(entree["chemin"])


def mesurer_ocr(entrees: list[dict], index: Path) -> dict[tuple[str, str], float]:
    """Chemin de `run_ocr_eval` : l'extracteur OCR appelé directement."""
    from app.extraction import ocr
    from evaluation.metrics import cer

    resultats = {}
    for entree in entrees:
        chemin = _chemin(index, entree)
        extraction = ocr.extraire(chemin.read_bytes())
        resultats[(entree["condition"], entree["id"])] = cer(
            entree["texte"], extraction.texte
        )
    return resultats


def mesurer_pipeline(entrees: list[dict], index: Path) -> dict[tuple[str, str], float]:
    """Chemin de `run_e2e_eval` : le pipeline complet, qui aboutit au même OCR."""
    from app import pipeline
    from evaluation.metrics import cer

    resultats = {}
    for entree in entrees:
        chemin = _chemin(index, entree)
        extraction, _, _ = pipeline.analyser(
            chemin.read_bytes(), "image/jpeg", chemin.name
        )
        resultats[(entree["condition"], entree["id"])] = cer(
            entree["texte"], extraction.texte
        )
    return resultats


def moyennes(mesures: dict[tuple[str, str], float]) -> dict[str, float]:
    par_condition: dict[str, list[float]] = defaultdict(list)
    for (condition, _), valeur in mesures.items():
        par_condition[condition].append(valeur)
    return {
        condition: statistics.fmean(par_condition[condition])
        for condition in CONDITIONS
        if par_condition.get(condition)
    }


def etat_opencv(moment: str) -> None:
    import cv2

    print(
        f"  {moment:<28} cv2 {cv2.__version__}  fils={cv2.getNumThreads()}  "
        f"OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS', '(absent)')}"
    )


def ecarts(
    gauche: dict[tuple[str, str], float],
    droite: dict[tuple[str, str], float],
    seuil: float = 0.01,
) -> list[tuple[str, str, float, float]]:
    divergents = [
        (condition, identifiant, gauche[(condition, identifiant)], valeur)
        for (condition, identifiant), valeur in droite.items()
        if abs(valeur - gauche.get((condition, identifiant), valeur)) > seuil
    ]
    divergents.sort(key=lambda ligne: abs(ligne[3] - ligne[2]), reverse=True)
    return divergents


def principal() -> None:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--index", type=Path, default=Path("../corpus/data/scans/index.jsonl"))
    analyseur.add_argument(
        "--par-condition",
        type=int,
        default=20,
        help="images par condition (0 = toutes). Le sous-ensemble est identique "
        "pour les quatre mesures, la comparaison reste donc valide.",
    )
    arguments = analyseur.parse_args()

    if not arguments.index.exists():
        raise SystemExit(f"{arguments.index} introuvable")

    entrees = charger(arguments.index, arguments.par_condition)
    print(f"{len(entrees)} images, {len(entrees) // len(CONDITIONS)} par condition\n")

    print("État d'OpenCV")
    etat_opencv("avant tout import")

    print("\nA1 — ocr.extraire seul, avant l'import du pipeline")
    a1 = mesurer_ocr(entrees, arguments.index)
    print("A2 — ocr.extraire seul, deuxième passe (test de déterminisme)")
    a2 = mesurer_ocr(entrees, arguments.index)

    print("\nImport de app.pipeline (charge torch et transformers)…")
    from app import pipeline  # noqa: F401

    etat_opencv("après l'import de torch")

    print("\nB — ocr.extraire seul, après l'import du pipeline")
    b = mesurer_ocr(entrees, arguments.index)
    print("C — pipeline.analyser, comme la campagne de bout en bout")
    c = mesurer_pipeline(entrees, arguments.index)

    print("\nCER moyen par condition")
    print(f"{'Condition':<12}{'A1':>10}{'A2':>10}{'B':>10}{'C':>10}")
    mesures = (moyennes(a1), moyennes(a2), moyennes(b), moyennes(c))
    for condition in CONDITIONS:
        if condition not in mesures[0]:
            continue
        colonnes = "".join(f"{serie[condition]:>10.4f}" for serie in mesures)
        print(f"{condition:<12}{colonnes}")

    print("\nDivergences par image (écart > 0,01)")
    for etiquette, gauche, droite in (
        ("A1 vs A2 (déterminisme)", a1, a2),
        ("A1 vs B  (effet de torch)", a1, b),
        ("B  vs C  (effet du pipeline)", b, c),
    ):
        divergents = ecarts(gauche, droite)
        print(f"  {etiquette:<30} {len(divergents)} image(s)")
        for condition, identifiant, avant, apres in divergents[:5]:
            print(f"      {condition:<10} {identifiant:<12} {avant:.4f} -> {apres:.4f}")

    print(
        "\nConclusion attendue : si A1 vs A2 est vide mais A1 vs B ne l'est pas, "
        "l'écart\nde la campagne de bout en bout vient de l'import de torch, pas "
        "des images."
    )


if __name__ == "__main__":
    principal()
