"""Production des tableaux du chapitre III (CSV + Markdown).

Les en-têtes de colonnes sont figés ici : ce sont exactement ceux des sections
3.1 et 3.2 du mémoire, pour que les tableaux soient reportables sans retouche.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from evaluation.metrics import (
    MANQUEE,
    ORDRE_NIVEAUX,
    SUPERFLUE,
    MatriceConfusion,
    Rapport,
    RapportE2E,
    Scores,
    sous_classements,
    verifier_cibles,
)

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


# --- Matrices de confusion ---------------------------------------------------


def tableau_confusion(matrice: MatriceConfusion) -> tuple[list[str], list[list[str]]]:
    """Met la matrice en table : lignes = attendu, colonnes = prédit.

    La colonne `(manquée)` porte les entités qu'aucune prédiction n'a
    recouvertes, la ligne `(superflue)` les prédictions qui ne recouvrent
    aucune entité. Sans ces deux marges, les totaux de ligne ne
    correspondraient plus au support et la table serait illisible.
    """
    etiquettes = matrice.etiquettes
    entetes = ["attendu \\ prédit", *etiquettes, MANQUEE, "total"]

    lignes: list[list[str]] = []
    for attendu in etiquettes:
        ligne = matrice.cellules.get(attendu, {})
        lignes.append(
            [
                attendu,
                *[str(ligne.get(predit, 0)) for predit in etiquettes],
                str(ligne.get(MANQUEE, 0)),
                str(matrice.total_ligne(attendu)),
            ]
        )

    if SUPERFLUE in matrice.cellules:
        ligne = matrice.cellules[SUPERFLUE]
        lignes.append(
            [
                SUPERFLUE,
                *[str(ligne.get(predit, 0)) for predit in etiquettes],
                "—",
                str(matrice.total_ligne(SUPERFLUE)),
            ]
        )

    return entetes, lignes


def _tableau_sous_classements(matrice: MatriceConfusion) -> tuple[list[str], list[list[str]]]:
    entetes = ["Niveau attendu", "Niveau attribué", "Occurrences"]
    releves = sous_classements(matrice)
    if not releves:
        return entetes, [["—", "—", "0"]]
    return entetes, [[a, p, str(n)] for a, p, n in releves]


def ecrire_rapport_confusion(
    par_type: MatriceConfusion,
    par_niveau: MatriceConfusion,
    sortie: Path,
    intitule: str = "confusion",
) -> None:
    """Écrit les deux matrices et le relevé des sous-classements."""
    sortie.mkdir(parents=True, exist_ok=True)

    entetes_type, lignes_type = tableau_confusion(par_type)
    entetes_niveau, lignes_niveau = tableau_confusion(par_niveau)
    entetes_sous, lignes_sous = _tableau_sous_classements(par_niveau)

    ecrire_csv(sortie / f"{intitule}_types.csv", entetes_type, lignes_type)
    ecrire_csv(sortie / f"{intitule}_niveaux.csv", entetes_niveau, lignes_niveau)
    ecrire_csv(sortie / f"{intitule}_sous_classements.csv", entetes_sous, lignes_sous)

    releves = sous_classements(par_niveau)
    total_sous = sum(n for _, _, n in releves)
    verdict = (
        "Aucun sous-classement : critère d'acceptation M5 satisfait."
        if total_sous == 0
        else f"**{total_sous} sous-classement(s)** — critère d'acceptation M5 NON satisfait."
    )

    markdown = "\n\n".join(
        [
            f"## Confusion par type d'entité (appariement {par_type.mode}, agnostique au type)",
            en_markdown(entetes_type, lignes_type),
            f"## Confusion par niveau de sensibilité (appariement {par_niveau.mode})",
            en_markdown(entetes_niveau, lignes_niveau),
            "## Sous-classements",
            "Un niveau attribué **inférieur** au niveau attendu ouvre l'accès à un "
            "rôle qui ne devrait pas l'avoir : c'est la seule moitié de la matrice "
            "qui constitue une faille. Le sur-classement ne fait que masquer trop.",
            en_markdown(entetes_sous, lignes_sous),
            verdict,
        ]
    )

    (sortie / f"{intitule}.md").write_text(markdown + "\n", encoding="utf-8")
    (sortie / f"{intitule}.json").write_text(
        json.dumps(
            {
                "parType": par_type.as_dict(),
                "parNiveau": par_niveau.as_dict(),
                "sousClassements": [
                    {"attendu": a, "attribue": p, "occurrences": n} for a, p, n in releves
                ],
                "totalSousClassements": total_sous,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(markdown)
    print(f"\nÉcrit dans {sortie}")


# --- Bout en bout par condition de dégradation -------------------------------

ENTETES_E2E = [
    "Condition",
    "Support",
    "Rappel",
    "Précision",
    "F2",
    "CER moyen",
    "Perdues OCR",
    "Non détectées",
]

def ecrire_rapport_e2e(rapport: RapportE2E, sortie: Path) -> None:
    """Écrit le rappel de bout en bout, ventilé par condition puis par type.

    Trois tables : une synthèse par condition, le rappel par condition × type
    d'entité, et le rappel par condition × niveau de sensibilité. La dernière
    est celle qui décide, puisque c'est le niveau que le portail confronte au
    rôle.
    """
    import statistics

    sortie.mkdir(parents=True, exist_ok=True)

    global_ = rapport.global_
    par_type = rapport.par_type
    par_niveau = rapport.par_niveau
    perdues = rapport.perdues_ocr
    non_detectees = rapport.non_detectees
    cers = rapport.cer
    tolerance = rapport.tolerance
    conditions = rapport.conditions

    # --- Synthèse par condition ---------------------------------------------
    lignes_synthese: list[list[str]] = []
    for condition in conditions:
        scores = global_[condition]
        valeurs_cer = cers.get(condition, [])
        lignes_synthese.append(
            [
                condition,
                str(scores.support),
                f"{scores.rappel:.3f}",
                f"{scores.precision:.3f}",
                f"{scores.f2:.3f}",
                f"{statistics.fmean(valeurs_cer):.3f}" if valeurs_cer else "—",
                str(sum(n for (c, _), n in perdues.items() if c == condition)),
                str(sum(n for (c, _), n in non_detectees.items() if c == condition)),
            ]
        )

    # --- Par condition x type ------------------------------------------------
    types = sorted({t for _, t in par_type})
    entetes_type = ["Type d'entité", *conditions]
    lignes_type = [
        [
            type_entite,
            *[
                f"{par_type[(c, type_entite)].rappel:.3f}"
                if (c, type_entite) in par_type
                else "—"
                for c in conditions
            ],
        ]
        for type_entite in types
    ]

    # --- Par condition x niveau ---------------------------------------------
    niveaux = [n for n in ORDRE_NIVEAUX if any((c, n) in par_niveau for c in conditions)]
    entetes_niveau = ["Niveau", *conditions]
    lignes_niveau = [
        [
            niveau,
            *[
                f"{par_niveau[(c, niveau)].rappel:.3f}" if (c, niveau) in par_niveau else "—"
                for c in conditions
            ],
        ]
        for niveau in niveaux
    ]

    ecrire_csv(sortie / "e2e_conditions.csv", ENTETES_E2E, lignes_synthese)
    ecrire_csv(sortie / "e2e_par_type.csv", entetes_type, lignes_type)
    ecrire_csv(sortie / "e2e_par_niveau.csv", entetes_niveau, lignes_niveau)

    critique_min = rapport.rappel_critique_minimal()
    verdict = (
        f"Rappel `critique` minimal sur l'ensemble des conditions : "
        f"**{critique_min:.3f}** (cible 0,95) — "
        + ("atteinte." if critique_min >= 0.95 else "**NON atteinte**.")
    )

    markdown = "\n\n".join(
        [
            "## Bout en bout — rappel par condition de dégradation",
            f"Appariement par valeur, tolérance {tolerance:.0%} des caractères. "
            "« Perdues OCR » : la valeur n'est plus reconnaissable dans le texte "
            "océrisé. « Non détectées » : elle y est, mais la détection l'a "
            "laissée passer — typiquement un validateur structurel qui rejette "
            "une valeur abîmée d'un caractère.",
            en_markdown(ENTETES_E2E, lignes_synthese),
            "## Rappel de bout en bout par type d'entité",
            en_markdown(entetes_type, lignes_type),
            "## Rappel de bout en bout par niveau de sensibilité",
            en_markdown(entetes_niveau, lignes_niveau),
            verdict,
        ]
    )

    (sortie / "e2e.md").write_text(markdown + "\n", encoding="utf-8")
    (sortie / "e2e.json").write_text(
        json.dumps(
            {
                "tolerance": tolerance,
                "parCondition": {
                    c: {
                        **global_[c].as_dict(),
                        "cerMoyen": round(statistics.fmean(cers[c]), 4) if cers.get(c) else None,
                    }
                    for c in conditions
                },
                "parType": {
                    f"{c}|{t}": s.as_dict() for (c, t), s in sorted(par_type.items())
                },
                "parNiveau": {
                    f"{c}|{n}": scores.as_dict()
                    for (c, n), scores in sorted(par_niveau.items())
                },
                "perduesOcr": {f"{c}|{t}": n for (c, t), n in sorted(perdues.items())},
                "nonDetectees": {f"{c}|{t}": n for (c, t), n in sorted(non_detectees.items())},
                "rappelCritiqueMinimal": round(critique_min, 4),
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
