"""Inventaire du corpus — tableaux descriptifs pour le mémoire.

    python corpus/stats.py --annotations corpus/data/annotations.jsonl

Produit la description du corpus attendue au chapitre III : volumétrie par
type de document, par format, par partition, et densité d'entités par type et
par niveau de sensibilité.

Le tableau « par partition » sert à vérifier une propriété précise : la
partition est faite **au niveau du document**, donc aucune entité du jeu de
test n'a pu être vue à l'entraînement. Si la même valeur apparaissait dans deux
partitions, les scores rapportés seraient optimistes — le script le signale.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

NIVEAUX = ("faible", "moyen", "eleve", "critique")
PARTITIONS = ("entrainement", "validation", "test")


def tableau(entetes: list[str], lignes: list[list[str]]) -> str:
    largeur = [len(e) for e in entetes]
    for ligne in lignes:
        for index, cellule in enumerate(ligne):
            largeur[index] = max(largeur[index], len(cellule))

    def formater(cellules: list[str]) -> str:
        return "| " + " | ".join(c.ljust(largeur[i]) for i, c in enumerate(cellules)) + " |"

    separateur = "|" + "|".join("-" * (taille + 2) for taille in largeur) + "|"
    return "\n".join([formater(entetes), separateur, *(formater(ligne) for ligne in lignes)])


def analyser(documents: list[dict]) -> str:
    sections: list[str] = []

    # --- Volumétrie ----------------------------------------------------------
    par_type = Counter(d["typeDocument"] for d in documents)
    par_format = Counter(Path(d["chemin"]).suffix.lstrip(".") for d in documents)
    par_partition = Counter(d["partition"] for d in documents)

    sections.append(
        "## Corpus — volumétrie\n\n"
        + tableau(
            ["Indicateur", "Valeur"],
            [
                ["Documents", str(len(documents))],
                ["Entités annotées", str(sum(len(d["entites"]) for d in documents))],
                [
                    "Entités par document (moyenne)",
                    f"{sum(len(d['entites']) for d in documents) / max(1, len(documents)):.1f}",
                ],
                [
                    "Caractères (total)",
                    str(sum(len(d["texte"]) for d in documents)),
                ],
            ],
        )
    )

    sections.append(
        "## Par type de document\n\n"
        + tableau(
            ["Type de document", "Documents", "Entités"],
            [
                [
                    type_document,
                    str(nombre),
                    str(
                        sum(
                            len(d["entites"])
                            for d in documents
                            if d["typeDocument"] == type_document
                        )
                    ),
                ]
                for type_document, nombre in sorted(par_type.items())
            ],
        )
    )

    sections.append(
        "## Par format de fichier\n\n"
        + tableau(
            ["Format", "Documents"],
            [[format_, str(nombre)] for format_, nombre in sorted(par_format.items())],
        )
    )

    # --- Partition -----------------------------------------------------------
    sections.append(
        "## Partition (au niveau du document)\n\n"
        + tableau(
            ["Partition", "Documents", "Part", "Entités"],
            [
                [
                    partition,
                    str(par_partition.get(partition, 0)),
                    f"{par_partition.get(partition, 0) / max(1, len(documents)):.0%}",
                    str(
                        sum(
                            len(d["entites"])
                            for d in documents
                            if d["partition"] == partition
                        )
                    ),
                ]
                for partition in PARTITIONS
            ],
        )
    )

    # --- Entités -------------------------------------------------------------
    par_type_entite: Counter[str] = Counter()
    par_niveau: Counter[str] = Counter()
    niveau_de_type: dict[str, str] = {}

    for document in documents:
        for entite in document["entites"]:
            par_type_entite[entite["type"]] += 1
            par_niveau[entite["niveau"]] += 1
            niveau_de_type[entite["type"]] = entite["niveau"]

    sections.append(
        "## Entités par type\n\n"
        + tableau(
            ["Type d'entité", "Niveau", "Occurrences", "Part"],
            [
                [
                    type_entite,
                    niveau_de_type.get(type_entite, "—"),
                    str(nombre),
                    f"{nombre / max(1, sum(par_type_entite.values())):.1%}",
                ]
                for type_entite, nombre in par_type_entite.most_common()
            ],
        )
    )

    sections.append(
        "## Entités par niveau de sensibilité\n\n"
        + tableau(
            ["Niveau", "Occurrences", "Part"],
            [
                [
                    niveau,
                    str(par_niveau.get(niveau, 0)),
                    f"{par_niveau.get(niveau, 0) / max(1, sum(par_niveau.values())):.1%}",
                ]
                for niveau in NIVEAUX
            ],
        )
    )

    sections.append(controle_fuite(documents))
    return "\n\n".join(sections)


def controle_fuite(documents: list[dict]) -> str:
    """Signale les valeurs présentes à la fois en entraînement et en test.

    Une valeur partagée n'invalide pas la partition — elle est faite au niveau
    du document, comme il se doit — mais elle indique que le générateur
    réutilise trop souvent les mêmes patronymes, ce qui rendrait le jeu de test
    plus facile qu'il ne devrait l'être.
    """
    par_partition: dict[str, set[str]] = defaultdict(set)
    for document in documents:
        for entite in document["entites"]:
            par_partition[document["partition"]].add(entite["valeur"].lower())

    entrainement = par_partition.get("entrainement", set())
    test = par_partition.get("test", set())
    communes = entrainement & test

    lignes = [
        ["Valeurs distinctes en entraînement", str(len(entrainement))],
        ["Valeurs distinctes en test", str(len(test))],
        ["Valeurs communes", str(len(communes))],
        [
            "Recouvrement du jeu de test",
            f"{len(communes) / max(1, len(test)):.1%}",
        ],
    ]

    avertissement = ""
    if test and len(communes) / len(test) > 0.25:
        avertissement = (
            "\n\n> Plus d'un quart des valeurs de test réapparaissent en "
            "entraînement. Élargir les listes de patronymes et de toponymes du "
            "générateur, sinon les scores rapportés seront optimistes."
        )

    return "## Contrôle de recouvrement entre partitions\n\n" + tableau(
        ["Indicateur", "Valeur"], lignes
    ) + avertissement


def principal() -> None:
    analyseur = argparse.ArgumentParser(description="Inventaire du corpus")
    analyseur.add_argument(
        "--annotations", type=Path, default=Path("corpus/data/annotations.jsonl")
    )
    analyseur.add_argument("--sortie", type=Path, default=None, help="fichier Markdown")
    arguments = analyseur.parse_args()

    if not arguments.annotations.exists():
        raise SystemExit(
            f"{arguments.annotations} introuvable — lancer d'abord corpus/generate.py"
        )

    with arguments.annotations.open(encoding="utf-8") as flux:
        documents = [json.loads(ligne) for ligne in flux]

    rapport = analyser(documents)
    print(rapport)

    if arguments.sortie:
        arguments.sortie.parent.mkdir(parents=True, exist_ok=True)
        arguments.sortie.write_text(rapport + "\n", encoding="utf-8")
        print(f"\nÉcrit dans {arguments.sortie}")


if __name__ == "__main__":
    principal()
