"""Normalisation du texte et table de correspondance des offsets.

Le point critique du module M3. La détection travaille sur du texte normalisé
(NFC, espaces réduits, ligatures décomposées) mais la protection doit écrire
dans le document **source**. Sans table de correspondance, le masquage
s'applique quelques caractères à côté et la donnée reste lisible.

`TexteNormalise.map_offsets[i]` donne l'offset, dans le texte source, du
caractère qui a produit le caractère normalisé `i`. La table compte
`len(texte) + 1` entrées : la dernière est la sentinelle de fin, ce qui rend
les bornes exclusives traduisibles sans cas particulier.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

# Ligatures typographiques : un caractère source produit plusieurs caractères
# normalisés, tous rattachés au même offset source.
LIGATURES: dict[str, str] = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    "Œ": "OE",
    "œ": "oe",
    "Æ": "AE",
    "æ": "ae",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    " ": " ",
    " ": " ",
    " ": " ",
    "﻿": "",
}


@dataclass
class TexteNormalise:
    """Texte normalisé accompagné de sa table de correspondance d'offsets."""

    texte: str
    map_offsets: list[int] = field(default_factory=list)

    def vers_source(self, position: int) -> int:
        """Traduit une position du texte normalisé en position source."""
        if not self.map_offsets:
            return position
        if position < 0:
            return self.map_offsets[0]
        if position >= len(self.map_offsets):
            return self.map_offsets[-1]
        return self.map_offsets[position]

    def span_source(self, debut: int, fin: int) -> tuple[int, int]:
        """Traduit un intervalle [debut, fin) normalisé en intervalle source."""
        return self.vers_source(debut), self.vers_source(fin)

    def __len__(self) -> int:
        return len(self.texte)


def normaliser(source: str) -> TexteNormalise:
    """Normalise `source` en conservant la correspondance des offsets.

    Opérations, dans l'ordre :
      1. décomposition des ligatures et des espaces typographiques ;
      2. composition NFC par grappe (caractère de base + marques combinantes) ;
      3. réduction des suites d'espaces à un espace, des sauts de ligne de
         mise en page à un saut, des paragraphes à deux sauts.
    """
    sortie: list[str] = []
    offsets: list[int] = []
    n = len(source)
    i = 0

    while i < n:
        car = source[i]

        # --- suites d'espaces -------------------------------------------
        if car.isspace():
            j = i
            nb_sauts = 0
            while j < n and source[j].isspace():
                # `\r\n` ne compte que pour un seul saut de ligne.
                suite_de_cr = source[j] == "\n" and j > i and source[j - 1] == "\r"
                if source[j] in "\n\r" and not suite_de_cr:
                    nb_sauts += 1
                j += 1
            if nb_sauts == 0:
                remplacement = " "
            elif nb_sauts == 1:
                remplacement = "\n"
            else:
                remplacement = "\n\n"
            for c in remplacement:
                sortie.append(c)
                offsets.append(i)
            i = j
            continue

        # --- grappe : base + marques combinantes -------------------------
        j = i + 1
        while j < n and unicodedata.combining(source[j]):
            j += 1
        grappe = unicodedata.normalize("NFC", source[i:j])
        grappe = "".join(LIGATURES.get(c, c) for c in grappe)

        for c in grappe:
            sortie.append(c)
            offsets.append(i)
        i = j

    offsets.append(n)  # sentinelle de fin
    return TexteNormalise(texte="".join(sortie), map_offsets=offsets)


def segmenter(
    texte: str, fenetre: int = 512, recouvrement: int = 64
) -> list[tuple[int, int]]:
    """Découpe `texte` en fenêtres glissantes d'environ `fenetre` mots.

    Retourne des intervalles de caractères `[debut, fin)`. Le recouvrement
    garantit qu'une entité à cheval sur une frontière est vue entière au moins
    une fois ; `detection.merge` élimine ensuite le doublon.

    L'approximation « un sous-mot ≈ 4 caractères » évite de charger un
    tokenizer ici : la segmentation ne sert qu'à borner la taille des entrées
    NER, la précision exacte de la fenêtre est sans effet sur le résultat.
    """
    if fenetre <= 0:
        return [(0, len(texte))]
    taille = max(1, fenetre * 4)
    pas = max(1, taille - recouvrement * 4)
    longueur = len(texte)
    if longueur <= taille:
        return [(0, longueur)]

    segments: list[tuple[int, int]] = []
    debut = 0
    while debut < longueur:
        fin = min(debut + taille, longueur)
        # aligner la coupure sur une frontière de mot lorsque c'est possible
        if fin < longueur:
            recul = texte.rfind(" ", debut + pas // 2, fin)
            if recul > debut:
                fin = recul
        segments.append((debut, fin))
        if fin >= longueur:
            break
        debut = max(debut + 1, fin - recouvrement * 4)
    return segments
