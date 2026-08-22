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

import unicodedata
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

    def recouvrement(self, autre: Empan) -> float:
        """Intersection sur union, pour departager plusieurs candidats."""
        intersection = min(self.fin, autre.fin) - max(self.debut, autre.debut)
        if intersection <= 0:
            return 0.0
        union = max(self.fin, autre.fin) - min(self.debut, autre.debut)
        return intersection / union if union else 0.0


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


# --- Matrice de confusion ----------------------------------------------------

# Marges de la matrice. Une entité de référence que rien n'a recouverte est
# « manquée » ; une prédiction qui ne recouvre aucune référence est « superflue ».
MANQUEE = "(manquée)"
SUPERFLUE = "(superflue)"


def apparier_par_position(
    reference: list[Empan], prediction: list[Empan], strict: bool = False
) -> tuple[list[tuple[Empan, Empan]], list[Empan], list[Empan]]:
    """Apparie référence et prédiction **sans tenir compte du type**.

    C'est la différence essentielle avec `apparier` : celle-ci n'apparie que
    des empans de même type, si bien qu'un IBAN prédit comme
    `NUM_PIECE_IDENTITE` produit un faux négatif ET un faux positif sans
    laisser voir qu'il s'agissait du **même empan**. Or c'est précisément cette
    information qu'une matrice de confusion doit exposer : le système a-t-il
    manqué la donnée, ou l'a-t-il trouvée et mal étiquetée ? Les deux erreurs
    n'ont pas les mêmes conséquences — la seconde protège quand même la donnée.

    L'appariement est glouton par recouvrement décroissant, et exclusif : un
    empan prédit ne peut valider qu'une seule reference.
    """
    candidats: list[tuple[float, int, int]] = []
    for index_reference, attendue in enumerate(reference):
        for index_prediction, proposee in enumerate(prediction):
            if strict:
                if proposee.debut == attendue.debut and proposee.fin == attendue.fin:
                    candidats.append((1.0, index_reference, index_prediction))
            elif attendue.chevauche(proposee):
                candidats.append(
                    (attendue.recouvrement(proposee), index_reference, index_prediction)
                )

    # Recouvrement décroissant ; à égalité, ordre du document pour rester
    # déterministe d'une exécution à l'autre.
    candidats.sort(key=lambda c: (-c[0], c[1], c[2]))

    references_prises: set[int] = set()
    predictions_prises: set[int] = set()
    apparies: list[tuple[Empan, Empan]] = []

    for _, index_reference, index_prediction in candidats:
        if index_reference in references_prises or index_prediction in predictions_prises:
            continue
        references_prises.add(index_reference)
        predictions_prises.add(index_prediction)
        apparies.append((reference[index_reference], prediction[index_prediction]))

    manquees = [e for i, e in enumerate(reference) if i not in references_prises]
    superflues = [e for i, e in enumerate(prediction) if i not in predictions_prises]
    return apparies, manquees, superflues


@dataclass
class MatriceConfusion:
    """Comptes `attendu -> prédit`, marges incluses."""

    cellules: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    intitule: str = "type"
    mode: str = "partiel"

    def ajouter(self, attendu: str, predit: str) -> None:
        self.cellules[attendu][predit] += 1

    @property
    def etiquettes(self) -> list[str]:
        """Étiquettes réelles, hors marges, triées."""
        vues = set(self.cellules)
        for ligne in self.cellules.values():
            vues.update(ligne)
        return sorted(vues - {MANQUEE, SUPERFLUE})

    def total_ligne(self, attendu: str) -> int:
        return sum(self.cellules.get(attendu, {}).values())

    def diagonale(self) -> int:
        return sum(self.cellules.get(e, {}).get(e, 0) for e in self.etiquettes)

    def hors_diagonale(self) -> int:
        """Empans trouvés au bon endroit mais mal étiquetés."""
        total = 0
        for attendu, ligne in self.cellules.items():
            if attendu == SUPERFLUE:
                continue
            for predit, nombre in ligne.items():
                if predit not in (attendu, MANQUEE):
                    total += nombre
        return total

    def confusions(self, minimum: int = 1) -> list[tuple[str, str, int]]:
        """Confusions réelles, les plus fréquentes d'abord."""
        listees = [
            (attendu, predit, nombre)
            for attendu, ligne in self.cellules.items()
            for predit, nombre in ligne.items()
            if attendu != predit
            and nombre >= minimum
            and not (attendu == SUPERFLUE and predit == MANQUEE)
        ]
        return sorted(listees, key=lambda c: -c[2])

    def as_dict(self) -> dict[str, object]:
        return {
            "intitule": self.intitule,
            "mode": self.mode,
            "cellules": {a: dict(ligne) for a, ligne in self.cellules.items()},
            "diagonale": self.diagonale(),
            "horsDiagonale": self.hors_diagonale(),
        }


def matrice_confusion(
    references: list[list[Empan]],
    predictions: list[list[Empan]],
    par_niveau: bool = False,
    strict: bool = False,
) -> MatriceConfusion:
    """Construit la matrice de confusion sur les types ou sur les niveaux."""
    if len(references) != len(predictions):
        raise ValueError("Références et prédictions doivent porter sur les mêmes documents")

    def cle(empan: Empan) -> str:
        return empan.niveau if par_niveau else empan.type_entite

    matrice = MatriceConfusion(
        intitule="niveau" if par_niveau else "type",
        mode="strict" if strict else "partiel",
    )

    for reference, prediction in zip(references, predictions, strict=True):
        apparies, manquees, superflues = apparier_par_position(reference, prediction, strict)
        for attendue, proposee in apparies:
            matrice.ajouter(cle(attendue), cle(proposee))
        for attendue in manquees:
            matrice.ajouter(cle(attendue), MANQUEE)
        for proposee in superflues:
            matrice.ajouter(SUPERFLUE, cle(proposee))

    return matrice


def _ordre_niveaux() -> dict[str, int]:
    """Ordre des niveaux, importé de `app.models` plutôt que recopié.

    La détection des sous-classements en dépend : deux sources de vérité pour
    l'ordre des niveaux divergeraient tôt ou tard, et le contrôle deviendrait
    silencieusement faux.
    """
    from app.models import ORDRE_NIVEAU

    # `.value` et non `str()` : sur un enum `(str, Enum)`, `str(membre)` rend
    # « NiveauSens.critique » et non « critique ». Les clés ne correspondaient
    # alors à aucun niveau, `sous_classements` renvoyait toujours une liste
    # vide, et le critère « sous-classement = 0 » de M5 était satisfait sans
    # rien vérifier — un contrôle qui passe toujours est pire qu'absent.
    return {niveau.value: rang for niveau, rang in ORDRE_NIVEAU.items()}


def sous_classements(matrice: MatriceConfusion) -> list[tuple[str, str, int]]:
    """Entités classées à un niveau INFÉRIEUR au niveau attendu.

    C'est la seule moitié de la matrice de niveaux qui constitue une faille :
    une donnée `critique` vue comme `moyen` devient lisible par un rôle qui ne
    devrait pas y accéder. Le sur-classement, lui, ne fait que masquer trop.
    Une entité manquée n'est pas un sous-classement mais un faux négatif, déjà
    compté par le rappel.
    """
    rangs = _ordre_niveaux()
    releves: list[tuple[str, str, int]] = []

    for attendu, ligne in matrice.cellules.items():
        if attendu not in rangs:
            continue
        for predit, nombre in ligne.items():
            if predit in rangs and rangs[predit] < rangs[attendu] and nombre:
                releves.append((attendu, predit, nombre))

    return sorted(releves, key=lambda r: (-rangs[r[0]], -r[2]))


# --- Appariement par valeur (bout en bout sur document dégradé) --------------
#
# Sur un scan, les offsets de la vérité terrain (texte d'origine) et ceux des
# prédictions (texte océrisé) ne vivent pas dans le même repère : l'OCR insère,
# supprime et confond des caractères. Apparier par position n'a donc aucun sens
# ici, et c'est la raison d'être de ce second mode d'appariement.
#
# La question mesurée devient : « le système a-t-il retrouvé cette donnée dans
# le texte qu'il a su lire ? » — c'est-à-dire, opérationnellement, a-t-il de
# quoi la masquer.

TOLERANCE_OCR = 0.25

# Ordre de présentation des conditions de dégradation, du plus favorable au
# plus défavorable pour l'OCR.
ORDRE_CONDITIONS = ("reference", "bruit", "flou", "rotation", "jpeg40")
ORDRE_NIVEAUX = ("faible", "moyen", "eleve", "critique")


def cle_comparaison(valeur: str) -> str:
    """Forme canonique d'une valeur pour la comparer malgré le bruit OCR.

    Casse, accents, espaces et ponctuation sont neutralisés. On ne corrige
    volontairement PAS les confusions propres à l'OCR (O/0, I/1, S/5) : les
    replier ici gonflerait le rappel en faisant passer pour trouvée une donnée
    que le système n'a pas su lire. Ce bruit-là est absorbé par la tolérance de
    distance d'édition, dont le niveau reste explicite et rapportable.
    """
    decompose = unicodedata.normalize("NFKD", valeur)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return "".join(c for c in sans_accents.casefold() if c.isalnum())


def similarite(a: str, b: str) -> float:
    """1 - distance d'édition normalisée, sur les formes canoniques."""
    gauche, droite = cle_comparaison(a), cle_comparaison(b)
    if not gauche and not droite:
        return 1.0
    if not gauche or not droite:
        return 0.0
    reference = max(len(gauche), len(droite))
    return 1.0 - distance_levenshtein(gauche, droite) / reference


def apparier_par_valeur(
    reference: list[Empan],
    prediction: list[Empan],
    valeurs_reference: list[str],
    valeurs_prediction: list[str],
    tolerance: float = TOLERANCE_OCR,
    exiger_le_type: bool = True,
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Apparie par valeur, du plus ressemblant au moins ressemblant.

    `tolerance` est la part de caractères pouvant différer : 0 exige une
    correspondance exacte après canonisation, 0,25 tolère qu'un quart des
    caractères soit abîmé par l'OCR.

    Retourne des **indices**, pour que l'appelant retrouve type et niveau.
    """
    seuil = 1.0 - tolerance
    candidats: list[tuple[float, int, int]] = []

    for index_reference, attendue in enumerate(reference):
        for index_prediction, proposee in enumerate(prediction):
            if exiger_le_type and proposee.type_entite != attendue.type_entite:
                continue
            score = similarite(
                valeurs_reference[index_reference], valeurs_prediction[index_prediction]
            )
            if score >= seuil:
                candidats.append((score, index_reference, index_prediction))

    candidats.sort(key=lambda c: (-c[0], c[1], c[2]))

    references_prises: set[int] = set()
    predictions_prises: set[int] = set()
    apparies: list[tuple[int, int, float]] = []

    for score, index_reference, index_prediction in candidats:
        if index_reference in references_prises or index_prediction in predictions_prises:
            continue
        references_prises.add(index_reference)
        predictions_prises.add(index_prediction)
        apparies.append((index_reference, index_prediction, score))

    manquees = [i for i in range(len(reference)) if i not in references_prises]
    superflues = [i for i in range(len(prediction)) if i not in predictions_prises]
    return apparies, manquees, superflues


def _trigrammes(valeur: str) -> set[str]:
    canonique = cle_comparaison(valeur)
    if len(canonique) < 3:
        return {canonique} if canonique else set()
    return {canonique[i : i + 3] for i in range(len(canonique) - 2)}


def presente_dans(texte: str, valeur: str, couverture: float = 0.7) -> bool:
    """Indique si `valeur` est reconnaissable dans `texte`, malgré le bruit OCR.

    Sert au **diagnostic** et non au score : il permet de départager deux
    causes très différentes de perte d'une entité —

      * la valeur n'est pas dans le texte océrisé -> l'OCR l'a détruite ;
      * elle y est mais n'a pas été détectée     -> c'est la détection qui a
        échoué, typiquement parce qu'un validateur structurel a rejeté une
        valeur abîmée d'un caractère.

    Le recouvrement de trigrammes est retenu plutôt qu'une recherche
    approximative de sous-chaîne : celle-ci coûterait O(n·m) sur des pages
    entières, pour un indicateur qui n'entre dans aucune métrique publiée.
    """
    attendus = _trigrammes(valeur)
    if not attendus:
        return False
    presents = _trigrammes(texte)
    return len(attendus & presents) / len(attendus) >= couverture


@dataclass
class RapportE2E:
    """Compteurs d'une campagne de bout en bout, ventilés par condition.

    Vit ici, avec les autres structures de mesure, plutôt que dans le lanceur :
    le module de rendu doit pouvoir en dépendre sans créer d'import circulaire.
    """

    global_: dict[str, Scores] = field(default_factory=lambda: defaultdict(Scores))
    par_type: dict[tuple[str, str], Scores] = field(
        default_factory=lambda: defaultdict(Scores)
    )
    par_niveau: dict[tuple[str, str], Scores] = field(
        default_factory=lambda: defaultdict(Scores)
    )
    # Décomposition des pertes : l'OCR a-t-il détruit la valeur, ou la détection
    # a-t-elle échoué sur une valeur restée lisible ?
    perdues_ocr: dict[tuple[str, str], int] = field(
        default_factory=lambda: defaultdict(int)
    )
    non_detectees: dict[tuple[str, str], int] = field(
        default_factory=lambda: defaultdict(int)
    )
    cer: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    tolerance: float = 0.0

    @property
    def conditions(self) -> list[str]:
        return [c for c in ORDRE_CONDITIONS if c in self.global_]

    def rappel_critique_minimal(self) -> float:
        """Pire rappel du niveau `critique` sur l'ensemble des conditions.

        C'est le chiffre qui engage le système : la cible de 0,95 doit tenir sur
        la condition la plus défavorable, pas en moyenne. Une moyenne peut
        masquer une condition où un IBAN sur deux passe en clair.
        """
        valeurs = [
            self.par_niveau[(condition, "critique")].rappel
            for condition in self.conditions
            if (condition, "critique") in self.par_niveau
        ]
        return min(valeurs) if valeurs else 0.0

    def compter(
        self,
        condition: str,
        references: list[Empan],
        valeurs_reference: list[str],
        predictions: list[Empan],
        valeurs_prediction: list[str],
        texte_ocr: str,
        tolerance: float = TOLERANCE_OCR,
    ) -> None:
        # Enregistrer la condition avant tout comptage : une condition dont
        # aucun document ne produit ni entité ni prédiction disparaîtrait sinon
        # du rapport, alors que ses images ont bien été traitées. Mieux vaut
        # l'afficher avec un support nul que la faire disparaître.
        _ = self.global_[condition]

        apparies, manquees, superflues = apparier_par_valeur(
            references, predictions, valeurs_reference, valeurs_prediction, tolerance
        )

        for index_reference, _, _ in apparies:
            attendue = references[index_reference]
            self.global_[condition].vp += 1
            self.par_type[(condition, attendue.type_entite)].vp += 1
            self.par_niveau[(condition, attendue.niveau)].vp += 1

        for index_reference in manquees:
            attendue = references[index_reference]
            self.global_[condition].fn += 1
            self.par_type[(condition, attendue.type_entite)].fn += 1
            self.par_niveau[(condition, attendue.niveau)].fn += 1

            cle = (condition, attendue.type_entite)
            if presente_dans(texte_ocr, valeurs_reference[index_reference]):
                self.non_detectees[cle] += 1
            else:
                self.perdues_ocr[cle] += 1

        for index_prediction in superflues:
            proposee = predictions[index_prediction]
            self.global_[condition].fp += 1
            self.par_type[(condition, proposee.type_entite)].fp += 1
            self.par_niveau[(condition, proposee.niveau)].fp += 1


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
