"""Structure de sortie commune aux extracteurs."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.extraction.normalize import TexteNormalise, normaliser
from app.models import MethodeExtraction


@dataclass
class BoiteMot:
    """Boîte englobante d'un mot reconnu par l'OCR.

    `debut` / `fin` sont des offsets dans le texte **normalisé**, ce qui permet
    de retrouver les boîtes à masquer à partir des positions d'entités.
    """

    debut: int
    fin: int
    x: int
    y: int
    largeur: int
    hauteur: int
    page: int = 0
    confiance: float = 0.0


@dataclass
class ResultatExtraction:
    """Texte extrait d'un document, prêt pour la détection."""

    normalise: TexteNormalise
    methode: MethodeExtraction
    brut: str = ""
    # Intervalles [debut, fin) dans le texte normalisé, un par page.
    pages: list[tuple[int, int]] = field(default_factory=list)
    nb_pages: int | None = None
    cer_estime: float | None = None
    boites: list[BoiteMot] = field(default_factory=list)

    @property
    def texte(self) -> str:
        return self.normalise.texte

    def page_de(self, position: int) -> int | None:
        """Numéro de page (1-indexé) contenant la position normalisée donnée."""
        for index, (debut, fin) in enumerate(self.pages):
            if debut <= position < fin:
                return index + 1
        return 1 if self.pages else None


def depuis_texte(
    brut: str,
    methode: MethodeExtraction,
    pages_brutes: list[str] | None = None,
    cer_estime: float | None = None,
) -> ResultatExtraction:
    """Construit un `ResultatExtraction` à partir de texte brut.

    Lorsque `pages_brutes` est fourni, les bornes de page sont recalculées
    dans le repère normalisé — c'est ce qui permet d'attribuer une page à
    chaque entité détectée.
    """
    normalise = normaliser(brut)

    pages: list[tuple[int, int]] = []
    if pages_brutes:
        curseur_source = 0
        bornes_source: list[tuple[int, int]] = []
        for page in pages_brutes:
            bornes_source.append((curseur_source, curseur_source + len(page)))
            curseur_source += len(page)

        # Traduction source -> normalisé : on cherche la première position
        # normalisée dont l'offset source atteint la borne.
        for debut_src, fin_src in bornes_source:
            debut_norm = _premiere_position(normalise, debut_src)
            fin_norm = _premiere_position(normalise, fin_src)
            pages.append((debut_norm, max(debut_norm, fin_norm)))

    return ResultatExtraction(
        normalise=normalise,
        methode=methode,
        brut=brut,
        pages=pages,
        nb_pages=len(pages_brutes) if pages_brutes else None,
        cer_estime=cer_estime,
    )


def _premiere_position(normalise: TexteNormalise, offset_source: int) -> int:
    """Première position normalisée dont l'offset source est >= `offset_source`."""
    table = normalise.map_offsets
    lo, hi = 0, len(table) - 1
    while lo < hi:
        milieu = (lo + hi) // 2
        if table[milieu] < offset_source:
            lo = milieu + 1
        else:
            hi = milieu
    return lo
