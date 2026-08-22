"""Classification des entités par niveau de sensibilité (M5).

Le niveau conditionne l'action du portail : c'est la seconde dimension de la
politique, à côté du rôle. Un sous-classement (une donnée critique rangée plus
bas) est une faille — il ouvre l'accès à un rôle qui ne devrait pas l'avoir.
Un sur-classement n'est qu'une gêne opérationnelle. La grille et l'ajustement
contextuel penchent donc systématiquement vers le haut.
"""

from __future__ import annotations

from app.models import ORDRE_NIVEAU, Entite, NiveauSens

# --- Grille type -> niveau ---------------------------------------------------

GRILLE: dict[str, NiveauSens] = {
    # faible — identifiants indirects, peu ré-identifiants seuls
    "LOCALITE": NiveauSens.faible,
    "ORGANISATION": NiveauSens.faible,
    "PRENOM": NiveauSens.faible,
    # moyen — identifiants directs courants
    "NOM_PERSONNE": NiveauSens.moyen,
    "ADRESSE_POSTALE": NiveauSens.moyen,
    "EMAIL": NiveauSens.moyen,
    # eleve — permettent de joindre ou de recouper la personne
    "TELEPHONE": NiveauSens.eleve,
    "DATE_NAISSANCE": NiveauSens.eleve,
    "NUM_CLIENT": NiveauSens.eleve,
    "PLAQUE_IMMAT": NiveauSens.eleve,
    "ADRESSE_IP": NiveauSens.eleve,
    # critique — pièces régaliennes et données financières
    "NUM_PIECE_IDENTITE": NiveauSens.critique,
    "IBAN": NiveauSens.critique,
    "CARTE_BANCAIRE": NiveauSens.critique,
    "DONNEE_SANTE": NiveauSens.critique,
}

NIVEAU_PAR_DEFAUT = NiveauSens.moyen

# --- Ajustement contextuel ---------------------------------------------------

FENETRE_CONTEXTE = 200

# Un nom seul est une mention. Un nom entouré d'une date de naissance et d'un
# numéro de pièce est une identité complète : le document est une pièce
# d'identité, pas un courrier qui cite quelqu'un.
TYPES_IDENTIFIANTS = {"DATE_NAISSANCE", "NUM_PIECE_IDENTITE", "IBAN", "CARTE_BANCAIRE"}

MINIMUM_CO_OCCURRENCES = 2


def niveau_de(type_entite: str) -> NiveauSens:
    """Niveau de base d'un type d'entité, `moyen` si le type est inconnu.

    Le défaut n'est volontairement pas `faible` : un type non répertorié est
    plus probablement une donnée personnelle mal nommée qu'une donnée inerte.
    """
    return GRILLE.get(type_entite.upper(), NIVEAU_PAR_DEFAUT)


def classer(entites: list[Entite]) -> list[Entite]:
    """Affecte un niveau à chaque entité, puis applique l'ajustement contextuel."""
    for entite in entites:
        entite.niveau = niveau_de(entite.typeEntite)

    _ajuster_contexte(entites)
    return entites


def _ajuster_contexte(entites: list[Entite]) -> None:
    """Élève NOM_PERSONNE à `eleve` en présence d'identifiants voisins."""
    identifiants = [e for e in entites if e.typeEntite in TYPES_IDENTIFIANTS]
    if not identifiants:
        return

    for entite in entites:
        if entite.typeEntite != "NOM_PERSONNE":
            continue
        voisins = {
            autre.typeEntite
            for autre in identifiants
            if _distance(entite, autre) <= FENETRE_CONTEXTE
        }
        if len(voisins) >= MINIMUM_CO_OCCURRENCES:
            entite.niveau = NiveauSens.eleve


def _distance(a: Entite, b: Entite) -> int:
    """Distance en caractères entre deux empans (0 s'ils se chevauchent)."""
    if a.fin <= b.debut:
        return b.debut - a.fin
    if b.fin <= a.debut:
        return a.debut - b.fin
    return 0


def niveau_maximum(entites: list[Entite]) -> NiveauSens | None:
    """`niveau_max` du document : maximum des niveaux de ses entités."""
    if not entites:
        return None
    return max(
        (e.niveau for e in entites),
        key=lambda n: ORDRE_NIVEAU.get(n, -1),
    )


def au_moins(niveau: NiveauSens, seuil: NiveauSens) -> bool:
    """Vrai si `niveau` est supérieur ou égal à `seuil`."""
    return ORDRE_NIVEAU.get(niveau, -1) >= ORDRE_NIVEAU.get(seuil, 99)
