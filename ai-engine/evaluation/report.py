"""Production des tableaux du chapitre III (CSV + Markdown).

Les en-têtes de colonnes sont figés ici : ce sont exactement ceux des sections
3.1 et 3.2 du mémoire, pour que les tableaux soient reportables sans retouche.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from evaluation.metrics import Rapport, Scores, verifier_cibles

ENTETES_DETECTION = [
    "Type d'entité",
    "Support",
    "Précision",
    "Rappel",
    "F1",
    "F2",
]

ENTETES_OCR = [
    "Condition",
    "Documents",
    "CER moyen",
    "CER médian",
    "CER p90",
]


def _ligne(nom: str, scores: Scores) -> list[str]:
    return [
        nom,
        str(scores.support),
        f"{scores.precision:.3f}",
        f"{scores.rappel:.3f}",
        f"{scores.f1:.3f}",
        f"{scores.f2:.3f}",
    ]


def tableau_detection(rapport: Rapport) -> list[list[str]]:
    """Ventilation par type d'entité, puis par niveau, puis global.

    La ventilation par type n'est pas décorative : un rappel global de 0,92
    peut masquer un rappel de 0,60 sur `NUM_PIECE_IDENTITE`, c'est-à-dire
    précisément sur la catégorie la plus critique (piège n°10).
    """
    lignes = [_ligne(type_entite, scores) for type_entite, scores in sorted(rapport.par_type.items())]
    lignes.append(["—", "—", "—", "—", "—", "—"])
    for niveau in ("faible", "moyen", "eleve", "critique"):
        if niveau in rapport.par_niveau:
            lignes.append(_ligne(f"[niveau] {niveau}", rapport.par_niveau[niveau]))
    lignes.append(["—", "—", "—", "—", "—", "—"])
    lignes.append(_ligne("GLOBAL", rapport.global_))
    return lignes


def en_markdown(entetes: list[str], lignes: list[list[str]]) -> str:
    largeur = [len(e) for e in entetes]
    for ligne in lignes:
        for index, cellule in enumerate(ligne):
            largeur[index] = max(largeur[index], len(cellule))

    def formater(cellules: list[str]) -> str:
        return "| " + " | ".join(c.ljust(largeur[i]) for i, c in enumerate(cellules)) + " |"

    separateur = "|" + "|".join("-" * (taille + 2) for taille in largeur) + "|"
    return "\n".join([formater(entetes), separateur, *(formater(ligne) for ligne in lignes)])


def ecrire_csv(chemin: Path, entetes: list[str], lignes: list[list[str]]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", newline="", encoding="utf-8") as flux:
        graveur = csv.writer(flux)
        graveur.writerow(entetes)
        graveur.writerows(lignes)


def ecrire_rapport_detection(
    rapport_strict: Rapport,
    rapport_partiel: Rapport,
    sortie: Path,
    intitule: str = "detection",
) -> None:
    sortie.mkdir(parents=True, exist_ok=True)

    lignes_strictes = tableau_detection(rapport_strict)
    lignes_partielles = tableau_detection(rapport_partiel)

    ecrire_csv(sortie / f"{intitule}_strict.csv", ENTETES_DETECTION, lignes_strictes)
    ecrire_csv(sortie / f"{intitule}_partiel.csv", ENTETES_DETECTION, lignes_partielles)

    cibles = verifier_cibles(rapport_strict)
    lignes_cibles = [
        [
            nom,
            f"{valeurs['valeur']:.3f}",
            f"{valeurs['cible']:.2f}",
            "atteinte" if valeurs["atteinte"] else "NON ATTEINTE",
        ]
        for nom, valeurs in cibles.items()
    ]
    ecrire_csv(
        sortie / f"{intitule}_cibles.csv",
        ["Indicateur", "Mesuré", "Cible", "Statut"],
        lignes_cibles,
    )

    markdown = "\n\n".join(
        [
            "## Détection — correspondance stricte des frontières",
            en_markdown(ENTETES_DETECTION, lignes_strictes),
            "## Détection — correspondance partielle",
            en_markdown(ENTETES_DETECTION, lignes_partielles),
            "## Cibles",
            en_markdown(["Indicateur", "Mesuré", "Cible", "Statut"], lignes_cibles),
        ]
    )
    (sortie / f"{intitule}.md").write_text(markdown + "\n", encoding="utf-8")
    (sortie / f"{intitule}.json").write_text(
        json.dumps(
            {
                "strict": rapport_strict.as_dict(),
                "partiel": rapport_partiel.as_dict(),
                "cibles": cibles,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(markdown)
    print(f"\nÉcrit dans {sortie}")


def ecrire_rapport_ocr(lignes: list[list[str]], sortie: Path) -> None:
    sortie.mkdir(parents=True, exist_ok=True)
    ecrire_csv(sortie / "ocr.csv", ENTETES_OCR, lignes)
    markdown = "## OCR — CER par condition de dégradation\n\n" + en_markdown(
        ENTETES_OCR, lignes
    )
    (sortie / "ocr.md").write_text(markdown + "\n", encoding="utf-8")
    print(markdown)
    print(f"\nÉcrit dans {sortie}")
