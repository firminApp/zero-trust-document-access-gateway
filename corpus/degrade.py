"""Rendu image et dégradations contrôlées du corpus.

Cinq conditions sur **les mêmes documents** — c'est ce qui permet d'imputer
l'écart de performance à la dégradation et non à la difficulté intrinsèque des
pièces. Chaque condition est une condition d'évaluation distincte :

  reference   rendu net, sans altération
  bruit       bruit gaussien additif (σ = 18)
  flou        flou gaussien 5×5
  rotation    rotation de 3°
  jpeg40      recompression JPEG à qualité 40

    python corpus/degrade.py --entree corpus/data/synthetic --sortie corpus/data/scans
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

CONDITIONS = ("reference", "bruit", "flou", "rotation", "jpeg40")

LARGEUR = 1240   # A4 à 150 ppp
HAUTEUR = 1754
MARGE = 70
INTERLIGNE = 26


def rendre(texte: str) -> np.ndarray:
    """Rend le texte en image, à la façon d'un document imprimé puis scanné."""
    image = np.full((HAUTEUR, LARGEUR, 3), 255, dtype=np.uint8)
    y = MARGE

    for ligne in texte.split("\n"):
        if y > HAUTEUR - MARGE:
            break
        cv2.putText(
            image,
            ligne[:110],
            (MARGE, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (15, 15, 15),
            1,
            cv2.LINE_AA,
        )
        y += INTERLIGNE
    return image


def appliquer(image: np.ndarray, condition: str, alea: np.random.Generator) -> np.ndarray:
    if condition == "reference":
        return image
    if condition == "bruit":
        bruit = alea.normal(0, 18, image.shape)
        return np.clip(image.astype(np.float64) + bruit, 0, 255).astype(np.uint8)
    if condition == "flou":
        return cv2.GaussianBlur(image, (5, 5), 0)
    if condition == "rotation":
        hauteur, largeur = image.shape[:2]
        matrice = cv2.getRotationMatrix2D((largeur / 2, hauteur / 2), 3.0, 1.0)
        return cv2.warpAffine(
            image,
            matrice,
            (largeur, hauteur),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
    if condition == "jpeg40":
        succes, encodee = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
        if not succes:
            return image
        return cv2.imdecode(encodee, cv2.IMREAD_COLOR)
    raise ValueError(f"Condition inconnue : {condition}")


def degrader(entree: Path, sortie: Path, limite: int | None, graine: int) -> None:
    annotations = entree.parent / "annotations.jsonl"
    if not annotations.exists():
        raise SystemExit(
            f"{annotations} introuvable — lancer d'abord corpus/generate.py"
        )

    alea = np.random.default_rng(graine)
    sortie.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, object]] = []

    with annotations.open(encoding="utf-8") as flux:
        documents = [json.loads(ligne) for ligne in flux]

    if limite:
        documents = documents[:limite]

    for document in documents:
        image = rendre(document["texte"])
        for condition in CONDITIONS:
            repertoire = sortie / condition
            repertoire.mkdir(parents=True, exist_ok=True)
            chemin = repertoire / f"{document['id']}.jpg"
            degradee = appliquer(image, condition, alea)
            cv2.imwrite(str(chemin), degradee, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            index.append(
                {
                    "id": document["id"],
                    "condition": condition,
                    # Chemin relatif à l'index lui-même : le répertoire de
                    # scans reste exploitable quel que soit le dossier depuis
                    # lequel l'évaluation est lancée.
                    "chemin": f"{condition}/{document['id']}.jpg",
                    "texte": document["texte"],
                    "partition": document["partition"],
                }
            )

    fichier_index = sortie / "index.jsonl"
    with fichier_index.open("w", encoding="utf-8") as flux:
        for ligne in index:
            flux.write(json.dumps(ligne, ensure_ascii=False) + "\n")

    print(
        f"{len(documents)} documents × {len(CONDITIONS)} conditions "
        f"= {len(index)} images dans {sortie}"
    )


def principal() -> None:
    analyseur = argparse.ArgumentParser(description="Dégradations contrôlées du corpus")
    analyseur.add_argument("--entree", type=Path, default=Path("corpus/data/synthetic"))
    analyseur.add_argument("--sortie", type=Path, default=Path("corpus/data/scans"))
    analyseur.add_argument("--limite", type=int, default=40)
    analyseur.add_argument("--graine", type=int, default=42)
    arguments = analyseur.parse_args()

    degrader(arguments.entree, arguments.sortie, arguments.limite, arguments.graine)


if __name__ == "__main__":
    principal()
