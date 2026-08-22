"""Prétraitement OCR — robustesse du redressement.

Le redressement est la seule étape du prétraitement qui peut ABÎMER l'image.
Faire pivoter une page d'un angle mesuré sur du bruit étale le grain en amas
que Tesseract lit comme du texte : mesuré à un CER de 5,9 sur le corpus, contre
0,13 sans redressement. D'où la règle : en cas de doute, ne rien faire.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.extraction import ocr

LARGEUR, HAUTEUR = 900, 600


def page_de_texte(angle: float = 0.0, bruit: float = 0.0) -> np.ndarray:
    """Fabrique une page de lignes horizontales, éventuellement inclinée/bruitée."""
    image = np.full((HAUTEUR, LARGEUR, 3), 255, dtype=np.uint8)
    for y in range(80, HAUTEUR - 80, 40):
        cv2.line(image, (60, y), (LARGEUR - 60, y), (10, 10, 10), 3)

    if angle:
        matrice = cv2.getRotationMatrix2D((LARGEUR / 2, HAUTEUR / 2), angle, 1.0)
        image = cv2.warpAffine(
            image, matrice, (LARGEUR, HAUTEUR),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )

    if bruit:
        alea = np.random.default_rng(42)
        image = np.clip(
            image.astype(np.float64) + alea.normal(0, bruit, image.shape), 0, 255
        ).astype(np.uint8)

    return image


def angles_hough(image: np.ndarray) -> np.ndarray:
    """Rejoue la mesure d'angle de la chaîne, pour inspecter sa dispersion."""
    binaire = ocr._binariser(ocr._en_niveaux_de_gris(image))
    contours = cv2.Canny(cv2.bitwise_not(binaire), 50, 150, apertureSize=3)
    lignes = cv2.HoughLinesP(
        contours, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10
    )
    if lignes is None:
        return np.array([])
    retenus = []
    for x1, y1, x2, y2 in np.asarray(lignes).reshape(-1, 4):
        if x2 == x1:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if -20 < angle < 20:
            retenus.append(float(angle))
    return np.array(retenus)


def dispersion(angles: np.ndarray) -> float:
    return float(np.median(np.abs(angles - np.median(angles)))) if len(angles) else 0.0


def test_les_lignes_s_accordent_sur_une_page_inclinee() -> None:
    angles = angles_hough(page_de_texte(angle=3.0))
    assert len(angles) >= ocr.MIN_LIGNES_REDRESSEMENT
    assert abs(np.median(angles)) > 2.0
    assert dispersion(angles) <= ocr.DISPERSION_MAX_DEGRES


def test_les_lignes_se_contredisent_sur_une_page_bruitee() -> None:
    """C'est ce désaccord qui doit faire renoncer au redressement."""
    angles = angles_hough(page_de_texte(bruit=40.0))
    if len(angles) >= ocr.MIN_LIGNES_REDRESSEMENT:
        assert dispersion(angles) > ocr.DISPERSION_MAX_DEGRES


def test_une_page_bruitee_n_est_pas_pivotee() -> None:
    binaire = ocr._binariser(ocr._en_niveaux_de_gris(page_de_texte(bruit=40.0)))
    assert np.array_equal(ocr._redresser(binaire), binaire)


def test_une_page_inclinee_est_bien_pivotee() -> None:
    binaire = ocr._binariser(ocr._en_niveaux_de_gris(page_de_texte(angle=3.0)))
    redresse = ocr._redresser(binaire)

    assert not np.array_equal(redresse, binaire)
    # Après redressement, les lignes restantes sont quasi horizontales.
    residuel = angles_hough(cv2.cvtColor(redresse, cv2.COLOR_GRAY2BGR))
    if len(residuel):
        assert abs(float(np.median(residuel))) < 1.0


def test_une_page_droite_reste_intacte() -> None:
    # Aucun angle à corriger : la chaîne ne doit pas réinterpoler l'image pour rien.
    binaire = ocr._binariser(ocr._en_niveaux_de_gris(page_de_texte()))
    assert np.array_equal(ocr._redresser(binaire), binaire)


def test_page_vide_sans_ligne_detectable() -> None:
    blanche = np.full((HAUTEUR, LARGEUR), 255, dtype=np.uint8)
    assert np.array_equal(ocr._redresser(blanche), blanche)


def test_l_ordre_du_pretraitement_est_respecte() -> None:
    """Niveaux de gris -> binarisation -> redressement -> filtre médian."""
    appels: list[str] = []
    originaux = (ocr._en_niveaux_de_gris, ocr._binariser, ocr._redresser, cv2.medianBlur)

    def tracer(nom, fonction):  # noqa: ANN001, ANN202
        def enveloppe(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            appels.append(nom)
            return fonction(*args, **kwargs)
        return enveloppe

    ocr._en_niveaux_de_gris = tracer("gris", originaux[0])
    ocr._binariser = tracer("binarisation", originaux[1])
    ocr._redresser = tracer("redressement", originaux[2])
    cv2.medianBlur = tracer("median", originaux[3])
    try:
        ocr.pretraiter(page_de_texte())
    finally:
        ocr._en_niveaux_de_gris, ocr._binariser, ocr._redresser = originaux[:3]
        cv2.medianBlur = originaux[3]

    assert appels == ["gris", "binarisation", "redressement", "median"]
