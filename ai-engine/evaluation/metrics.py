"""Métriques d'évaluation au niveau de l'entité.

Héritage des campagnes i2b2 de dé-identification : on ne mesure pas au niveau
du token mais de l'entité, avec correspondance **stricte** des frontières, et
on rapporte séparément une variante en correspondance partielle.

    precision = VP / (VP + FP)
    rappel    = VP / (VP + FN)
    F1        = 2·P·R / (P + R)
    F2        = 5·P·R / (4·P + R)      <- métrique de DÉCISION

Le F2 pondère le rappel quatre fois plus que la précision. C'est le bon
arbitrage ici parce que les erreurs sont asymétriques : un faux positif masque
une donnée inutilement — visible, réversible, on s'en plaint ; un faux négatif
laisse un IBAN en clair — invisible, et c'est une fuite. Le F1, indifférent à
cette asymétrie, n'est rapporté que pour la comparaison avec la littérature.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Empan:
    """Une entité, référence ou prédiction."""

    type_entite: str
    debut: int
    fin: int
    niveau: str = "moyen"

    def chevauche(self, autre: Empan) -> bool:
        return self.debut < autre.fin and autre.debut < self.fin


@dataclass
class Scores:
    vp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denominateur = self.vp + self.fp
        return self.vp / denominateur if denominateur else 0.0

    @property
    def rappel(self) -> float:
        denominateur = self.vp + self.fn
        return self.vp / denominateur if denominateur else 0.0

    @property
    def f1(self) -> float:
        return self._f_beta(1.0)

    @property
    def f2(self) -> float:
        return self._f_beta(2.0)

    def _f_beta(self, beta: float) -> float:
        precision, rappel = self.precision, self.rappel
        if precision == 0.0 and rappel == 0.0:
            return 0.0
        beta2 = beta * beta
        return (1 + beta2) * precision * rappel / (beta2 * precision + rappel)

    @property
    def support(self) -> int:
        """Nombre d'entités de référence — indispensable pour lire un score."""
        return self.vp + self.fn

    def as_dict(self) -> dict[str, float | int]:
        return {
            "vp": self.vp,
            "fp": self.fp,
            "fn": self.fn,
            "support": self.support,
            "precision": round(self.precision, 4),
            "rappel": round(self.rappel, 4),
            "f1": round(self.f1, 4),
            "f2": round(self.f2, 4),
        }

    def __add__(self, autre: Scores) -> Scores:
        return Scores(self.vp + autre.vp, self.fp + autre.fp, self.fn + autre.fn)


@dataclass
class Rapport:
    """Résultat complet d'une campagne, ventilé par type et par niveau."""

    global_: Scores = field(default_factory=Scores)
    par_type: dict[str, Scores] = field(default_factory=lambda: defaultdict(Scores))
    par_niveau: dict[str, Scores] = field(default_factory=lambda: defaultdict(Scores))
    mode: str = "strict"

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "global": self.global_.as_dict(),
            "parType": {t: s.as_dict() for t, s in sorted(self.par_type.items())},
            "parNiveau": {n: s.as_dict() for n, s in sorted(self.par_niveau.items())},
        }


def apparier(
    reference: list[Empan], prediction: list[Empan], strict: bool = True
) -> tuple[list[tuple[Empan, Empan]], list[Empan], list[Empan]]:
    """Apparie prédictions et références.

    En mode strict, les frontières **et** le type doivent coïncider. En mode
    partiel, un chevauchement de même type suffit — ce qui répond à la
    question pratique « la donnée a-t-elle été repérée ? », indépendamment du
    cadrage exact de l'empan.

    Un appariement est exclusif : une prédiction ne peut valider qu'une seule
    référence, sinon un empan très large gonflerait artificiellement le rappel.
    """
    restantes = list(prediction)
    apparies: list[tuple[Empan, Empan]] = []
    manquees: list[Empan] = []

    for attendue in reference:
        candidate = None
        for proposee in restantes:
            if proposee.type_entite != attendue.type_entite:
                continue
            if strict:
                if proposee.debut == attendue.debut and proposee.fin == attendue.fin:
                    candidate = proposee
                    break
            elif proposee.chevauche(attendue):
                candidate = proposee
                break

        if candidate is None:
            manquees.append(attendue)
        else:
            restantes.remove(candidate)
            apparies.append((attendue, candidate))

    return apparies, manquees, restantes


def evaluer(
    references: list[list[Empan]],
    predictions: list[list[Empan]],
    strict: bool = True,
) -> Rapport:
    """Évalue un jeu de documents. Les deux listes sont alignées par index."""
    if len(references) != len(predictions):
        raise ValueError("Références et prédictions doivent porter sur les mêmes documents")

    rapport = Rapport(mode="strict" if strict else "partiel")

    for reference, prediction in zip(references, predictions, strict=True):
        apparies, manquees, superflues = apparier(reference, prediction, strict)

        for attendue, _ in apparies:
            rapport.global_.vp += 1
            rapport.par_type[attendue.type_entite].vp += 1
            rapport.par_niveau[attendue.niveau].vp += 1

        for attendue in manquees:
            rapport.global_.fn += 1
            rapport.par_type[attendue.type_entite].fn += 1
            rapport.par_niveau[attendue.niveau].fn += 1

        for proposee in superflues:
            rapport.global_.fp += 1
            rapport.par_type[proposee.type_entite].fp += 1
            rapport.par_niveau[proposee.niveau].fp += 1

    return rapport


# --- CER (OCR) ---------------------------------------------------------------


def distance_levenshtein(a: str, b: str) -> int:
    """Distance d'édition, calculée sur deux lignes seulement."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    precedente = list(range(len(b) + 1))
    for i, car_a in enumerate(a, start=1):
        courante = [i]
        for j, car_b in enumerate(b, start=1):
            courante.append(
                min(
                    precedente[j] + 1,          # suppression
                    courante[j - 1] + 1,        # insertion
                    precedente[j - 1] + (car_a != car_b),  # substitution
                )
            )
        precedente = courante
    return precedente[-1]


def cer(reference: str, hypothese: str) -> float:
    """Character Error Rate = distance d'édition / longueur de la référence."""
    reference_normalisee = " ".join(reference.split())
    hypothese_normalisee = " ".join(hypothese.split())
    if not reference_normalisee:
        return 0.0 if not hypothese_normalisee else 1.0
    return distance_levenshtein(reference_normalisee, hypothese_normalisee) / len(
        reference_normalisee
    )


# --- Cibles du mémoire -------------------------------------------------------

CIBLES = {
    "rappel_global": 0.90,
    "rappel_critique": 0.95,
    "f2_global": 0.90,
    "cer_max": 0.10,
}


def verifier_cibles(rapport: Rapport) -> dict[str, dict[str, float | bool]]:
    """Confronte un rapport aux cibles annoncées au chapitre III."""
    critique = rapport.par_niveau.get("critique", Scores())
    return {
        "rappel_global": {
            "valeur": round(rapport.global_.rappel, 4),
            "cible": CIBLES["rappel_global"],
            "atteinte": rapport.global_.rappel >= CIBLES["rappel_global"],
        },
        "rappel_critique": {
            "valeur": round(critique.rappel, 4),
            "cible": CIBLES["rappel_critique"],
            "atteinte": critique.rappel >= CIBLES["rappel_critique"],
        },
        "f2_global": {
            "valeur": round(rapport.global_.f2, 4),
            "cible": CIBLES["f2_global"],
            "atteinte": rapport.global_.f2 >= CIBLES["f2_global"],
        },
    }
