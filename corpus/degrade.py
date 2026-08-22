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
import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

CONDITIONS = ("reference", "bruit", "flou", "rotation", "jpeg40")

LARGEUR = 1240   # A4 à 150 ppp
HAUTEUR = 1754
MARGE = 70
INTERLIGNE = 26
CORPS = 20
ENCRE = (15, 15, 15)

# Le rendu doit utiliser une vraie police TrueType, et non la police vectorielle
# `FONT_HERSHEY_SIMPLEX` d'OpenCV. Celle-ci trace des segments et perd le point
# du « i » : Tesseract lit « DOMACILE », « soussgné », « Bneta Ndaye ». Le CER
# mesuré était alors cinq fois trop élevé (0,133 contre 0,025 sur la même page)
# et décrivait le générateur d'images, pas la chaîne OCR — exactement le genre
# de mesure qui fait conclure à tort que le prétraitement est insuffisant.
POLICES_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",                  # Debian (image Docker)
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",                     # macOS
    "/Library/Fonts/Arial Unicode.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",                                  # Windows
)


def charger_police(taille: int = CORPS) -> ImageFont.FreeTypeFont | None:
    """Première police TrueType disponible, ou None si aucune n'est installée."""
    for chemin in POLICES_CANDIDATES:
        if Path(chemin).exists():
            try:
                return ImageFont.truetype(chemin, taille)
            except OSError:
                continue
    return None


def rendre(texte: str, police: ImageFont.FreeTypeFont | None = None) -> np.ndarray:
    """Rend le texte en image, à la façon d'un document imprimé puis scanné."""
    lignes = texte.split("\n")

    if police is None:
        logger.warning(
            "Aucune police TrueType trouvée : repli sur la police vectorielle "
            "d'OpenCV. Le CER mesuré ne sera PAS représentatif de la chaîne "
            "OCR — installer fonts-dejavu-core (Debian) avant de publier des "
            "résultats."
        )
        image = np.full((HAUTEUR, LARGEUR, 3), 255, dtype=np.uint8)
        y = MARGE
        for ligne in lignes:
            if y > HAUTEUR - MARGE:
                break
            cv2.putText(
                image, ligne[:110], (MARGE, y), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, ENCRE, 1, cv2.LINE_AA,
            )
            y += INTERLIGNE
        return image

    page = Image.new("RGB", (LARGEUR, HAUTEUR), "white")
    dessin = ImageDraw.Draw(page)
    y = MARGE
    for ligne in lignes:
        if y > HAUTEUR - MARGE:
            break
        dessin.text((MARGE, y), ligne[:110], font=police, fill=ENCRE)
        y += INTERLIGNE

    return cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)


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
    police = charger_police()
    sortie.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, object]] = []

    with annotations.open(encoding="utf-8") as flux:
        documents = [json.loads(ligne) for ligne in flux]

    if limite:
        documents = documents[:limite]

    for document in documents:
        image = rendre(document["texte"], police)
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    analyseur = argparse.ArgumentParser(description="Dégradations contrôlées du corpus")
    analyseur.add_argument("--entree", type=Path, default=Path("corpus/data/synthetic"))
    analyseur.add_argument("--sortie", type=Path, default=Path("corpus/data/scans"))
    analyseur.add_argument("--limite", type=int, default=40)
    analyseur.add_argument("--graine", type=int, default=42)
    arguments = analyseur.parse_args()

    degrader(arguments.entree, arguments.sortie, arguments.limite, arguments.graine)


if __name__ == "__main__":
    principal()
