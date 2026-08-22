"""Réparation des jetons disloqués par l'OCR.

Tesseract insère des espaces autour de la ponctuation : `binetandiaye@mail.bj`
ressort en `binetandiaye @mall .bj`. Les motifs de `rules.py` supposent des
jetons bien formés et ne reconnaissent alors plus rien — mesuré à un rappel
`EMAIL` de 0,214 sur des scans nets, alors que le CER n'y est que de 0,066.

On produit donc une variante du texte où ces espaces parasites sont retirés, et
on y rejoue les règles. La variante ne sert **qu'à la détection** : les empans
trouvés sont immédiatement retraduits dans le texte normalisé, seul repère
depuis lequel la protection peut écrire.

Deux garde-fous délibérés :

  * seuls les espaces **adjacents à une ponctuation interne** sont retirés, et
    uniquement quand les deux côtés sont alphanumériques. Retirer tous les
    espaces recollerait des mots sans rapport et fabriquerait des détections ;
  * la variante n'alimente pas la NER. Celle-ci travaille sur le texte
    d'origine, dont la ponctuation et les espaces portent le contexte dont elle
    a besoin.
"""

from __future__ import annotations

import re

from app.extraction.normalize import TexteNormalise

# Ponctuation qui, dans un jeton, ne doit jamais être entourée d'espaces :
# séparateurs d'adresse électronique, de domaine, de date et de référence.
PONCTUATION_INTERNE = "@.-/"

# `X <espaces> @ <espaces> Y` où X et Y sont alphanumériques.
#
# Le motif tolère zéro espace — un groupe optionnel ne peut pas exiger « au
# moins un des deux côtés » sans dupliquer le groupe de capture. La condition
# est donc vérifiée en code par `_disloque`, qui écarte les correspondances
# n'ayant aucun espace à retirer : sans cela, tout jeton déjà bien formé
# (`awa@exemple.sn`) serait vu comme à réparer, déclenchant un second passage
# inutile des règles et des détections en double.
_MOTIF_ESPACES_PARASITES = re.compile(
    r"(?<=[0-9A-Za-zÀ-ÖØ-öø-ÿ])"
    r"[ \t]*([" + re.escape(PONCTUATION_INTERNE) + r"])[ \t]*"
    r"(?=[0-9A-Za-zÀ-ÖØ-öø-ÿ])"
)


def _disloque(correspondance: re.Match[str]) -> bool:
    """Vrai si la correspondance comporte réellement un espace à retirer."""
    return correspondance.end() - correspondance.start() > 1


# Second mécanisme, distinct du premier : l'OCR ne décale pas toujours le point,
# il le **remplace par un espace**. `binetandiaye@mail.bj` ressort en
# `binetandiaye @mall bJ` — il n'y a donc aucune ponctuation à recoller, le
# point a purement disparu. On le restitue, mais uniquement après un `@` et
# devant ce qui a la forme d'un domaine de premier niveau : hors de ce contexte,
# transformer un espace en point fabriquerait des jetons de toutes pièces.
# L'extension peut n'avoir qu'un caractère : elle est aussi rognée par l'OCR
# (`@poste a` pour `@poste.ci`).
# Le libellé admet tout caractère non blanc, pour la même raison que
# `MOTIF_EMAIL_OCR` : l'OCR insère des caractères parasites dans le domaine
# (`poste` -> `pos'e`), et les énumérer serait sans fin. La structure reste
# contraignante — un `@`, un libellé sans espace, puis une extension courte.
# Le libellé exclut le point ET démarre juste après le `@`. Sans cette double
# contrainte, une adresse DÉJÀ complète voyait un point s'ajouter au mot
# suivant : `awa.diouf@exemple.sn pour la suite` devenait
# `awa.diouf@exemple.sn.pour`, et le masquage débordait sur le texte courant.
# La réparation ne doit agir que sur un domaine dépourvu de point.
_MOTIF_DOMAINE_SANS_POINT = re.compile(
    r"(?<=@)([^\s@.]{2,})[ \t]+([A-Za-z]{1,4})(?![0-9A-Za-z])"
)


def _composer(externe: TexteNormalise, interne: TexteNormalise) -> TexteNormalise:
    """Compose deux tables d'offsets : texte2 -> texte1 -> texte0.

    Sans cette composition, un second passage de réparation rendrait des
    positions relatives au texte déjà réparé, et la protection écrirait au
    mauvais endroit dans le document d'origine.
    """
    return TexteNormalise(
        texte=interne.texte,
        map_offsets=[externe.map_offsets[position] for position in interne.map_offsets],
    )


def _restituer_point_de_domaine(texte: str) -> TexteNormalise:
    """Remplace par un point l'espace qui sépare un domaine de son extension."""
    sortie: list[str] = []
    offsets: list[int] = []
    curseur = 0

    for correspondance in _MOTIF_DOMAINE_SANS_POINT.finditer(texte):
        for position in range(curseur, correspondance.end(1)):
            sortie.append(texte[position])
            offsets.append(position)

        # Le point occupe la place du premier espace : un caractère pour un
        # caractère, la table reste strictement croissante.
        sortie.append(".")
        offsets.append(correspondance.end(1))

        for position in range(correspondance.start(2), correspondance.end(2)):
            sortie.append(texte[position])
            offsets.append(position)

        curseur = correspondance.end(2)

    for position in range(curseur, len(texte)):
        sortie.append(texte[position])
        offsets.append(position)

    offsets.append(len(texte))
    return TexteNormalise(texte="".join(sortie), map_offsets=offsets)


def reparer(texte: str) -> TexteNormalise:
    """Retire les espaces parasites, en conservant la correspondance d'offsets.

    Réutilise `TexteNormalise` : c'est exactement le même contrat — un texte de
    travail plus une table qui ramène chaque position à la source. Redéfinir la
    structure ici créerait deux mécanismes d'offsets à maintenir, pour le bug le
    plus coûteux à découvrir tard.
    """
    espaces_retires = _retirer_espaces_parasites(texte)
    points_restitues = _restituer_point_de_domaine(espaces_retires.texte)
    return _composer(espaces_retires, points_restitues)


def _retirer_espaces_parasites(texte: str) -> TexteNormalise:
    sortie: list[str] = []
    offsets: list[int] = []
    curseur = 0

    for correspondance in _MOTIF_ESPACES_PARASITES.finditer(texte):
        if not _disloque(correspondance):
            continue

        # Le segment intact qui précède.
        for position in range(curseur, correspondance.start()):
            sortie.append(texte[position])
            offsets.append(position)

        # La ponctuation seule, rattachée à sa position réelle.
        ponctuation = correspondance.group(1)
        sortie.append(ponctuation)
        offsets.append(correspondance.start(1))

        curseur = correspondance.end()

    for position in range(curseur, len(texte)):
        sortie.append(texte[position])
        offsets.append(position)

    offsets.append(len(texte))  # sentinelle de fin
    return TexteNormalise(texte="".join(sortie), map_offsets=offsets)


def vaut_la_peine(texte: str) -> bool:
    """Indique si le texte comporte des jetons à réparer.

    Évite un second passage complet des règles quand l'OCR n'a rien disloqué,
    ce qui est le cas courant sur un scan propre.
    """
    if any(
        _disloque(correspondance)
        for correspondance in _MOTIF_ESPACES_PARASITES.finditer(texte)
    ):
        return True
    return _MOTIF_DOMAINE_SANS_POINT.search(texte) is not None
