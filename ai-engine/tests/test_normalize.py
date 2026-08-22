"""Table de correspondance des offsets — le test à écrire en premier (piège n°1).

Si un offset normalisé ne se retraduit pas exactement en offset source, le
masquage s'applique à côté et la donnée reste lisible dans le document rendu.
Tout le reste de la chaîne repose sur cette propriété.
"""

from __future__ import annotations

import pytest

from app.extraction.normalize import normaliser, segmenter


def test_texte_simple_est_inchange() -> None:
    resultat = normaliser("Awa Diouf")
    assert resultat.texte == "Awa Diouf"
    assert resultat.map_offsets == list(range(10))


@pytest.mark.parametrize(
    "source",
    [
        "Nom : Awa Diouf",
        "Awa    Diouf",                       # espaces multiples
        "Awa\t\tDiouf",                       # tabulations
        "Ligne 1\n\n\n\nLigne 2",             # sauts de mise en page
        "Œuvre ﬁnancière de M. Kofi",         # ligatures
        "Adresse : 12, rue de la Paix\r\nDakar",
        "Jean-Pierre  N’Diaye — Cotonou",     # apostrophe et tiret typographiques
        "élève",                  # combinantes -> NFC
        "  début et fin espacés   ",
    ],
)
def test_chaque_offset_normalise_se_retraduit(source: str) -> None:
    resultat = normaliser(source)
    assert len(resultat.map_offsets) == len(resultat.texte) + 1
    # La table est croissante : l'ordre du document est préservé.
    assert all(
        resultat.map_offsets[i] <= resultat.map_offsets[i + 1]
        for i in range(len(resultat.map_offsets) - 1)
    )
    # Tout offset reste dans les bornes du texte source.
    assert all(0 <= o <= len(source) for o in resultat.map_offsets)


def test_span_source_retrouve_la_valeur_exacte() -> None:
    """Le cas qui compte : retrouver la sous-chaîne source d'une entité."""
    source = "Contact :  awa.diouf@example.sn  \n\n  Téléphone : +221 77 123 45 67"
    resultat = normaliser(source)

    debut = resultat.texte.index("awa.diouf@example.sn")
    fin = debut + len("awa.diouf@example.sn")
    debut_src, fin_src = resultat.span_source(debut, fin)

    assert source[debut_src:fin_src] == "awa.diouf@example.sn"


def test_span_source_avec_ligature() -> None:
    source = "Dossier ﬁnancier de Kofi Mensah"
    resultat = normaliser(source)
    assert "financier" in resultat.texte

    debut = resultat.texte.index("Kofi Mensah")
    fin = debut + len("Kofi Mensah")
    debut_src, fin_src = resultat.span_source(debut, fin)
    assert source[debut_src:fin_src] == "Kofi Mensah"


def test_span_source_apres_espaces_reduits() -> None:
    source = "Nom :     Fatou     Sow     ; suite"
    resultat = normaliser(source)
    assert resultat.texte == "Nom : Fatou Sow ; suite"

    debut = resultat.texte.index("Fatou Sow")
    fin = debut + len("Fatou Sow")
    debut_src, fin_src = resultat.span_source(debut, fin)

    # L'empan source recouvre les espaces internes que la normalisation a
    # réduits : c'est exactement ce qu'il faut remplacer pour que rien ne
    # subsiste dans le document rendu.
    assert source[debut_src:fin_src] == "Fatou     Sow"
    assert normaliser(source[debut_src:fin_src]).texte == "Fatou Sow"


def test_toutes_les_sous_chaines_alphanumeriques_se_retraduisent() -> None:
    """Balayage exhaustif : chaque mot du texte normalisé doit se retrouver."""
    source = (
        "ATTESTATION\n\n"
        "Je soussigné(e)   Mamadou   FALL, né le 03/07/1988 à Thiès,\n"
        "titulaire de la CNI n° 1988070312345, déclare que\n\n\n"
        "l'IBAN SN91SN0100152000048500000765 est bien le mien.\n"
        "Courriel : mamadou.fall@exemple.sn — Tél : +221 77 555 44 33\n"
    )
    resultat = normaliser(source)

    for mot in ("Mamadou", "FALL", "03/07/1988", "1988070312345", "Thiès"):
        debut = resultat.texte.index(mot)
        debut_src, fin_src = resultat.span_source(debut, debut + len(mot))
        assert source[debut_src:fin_src] == mot, mot


def test_sentinelle_de_fin() -> None:
    source = "abc"
    resultat = normaliser(source)
    assert resultat.map_offsets[-1] == len(source)
    assert resultat.span_source(0, len(resultat.texte)) == (0, 3)


def test_texte_vide() -> None:
    resultat = normaliser("")
    assert resultat.texte == ""
    assert resultat.map_offsets == [0]


# --- Segmentation ------------------------------------------------------------


def test_segmentation_courte_produit_un_seul_segment() -> None:
    assert segmenter("court", 512, 64) == [(0, 5)]


def test_segmentation_couvre_tout_le_texte_avec_recouvrement() -> None:
    texte = " ".join(f"mot{i}" for i in range(3000))
    segments = segmenter(texte, 512, 64)

    assert len(segments) > 1
    assert segments[0][0] == 0
    assert segments[-1][1] == len(texte)
    # Chaque segment reprend là où le précédent n'avait pas fini : aucun trou.
    for precedent, suivant in zip(segments, segments[1:], strict=False):
        assert suivant[0] < precedent[1]


# --- Recadrage des empans NER ------------------------------------------------


def test_recadrage_retire_l_espace_de_tete() -> None:
    """Régression : les offsets SentencePiece incluent l'espace précédent.

    CamemBERT rend `' Awa Diouf'` pour `'Awa Diouf'`. Non recadré, l'empan est
    décalé d'un caractère : le masquage efface l'espace et laisse le dernier
    caractère de la donnée visible.
    """
    from app.detection.ner import recadrer

    texte = "de la demande de Awa Diouf.\n"
    debut_brut = texte.index(" Awa Diouf")
    fin_brut = debut_brut + len(" Awa Diouf")

    debut, fin, valeur = recadrer(texte, debut_brut, fin_brut)

    assert valeur == "Awa Diouf"
    assert texte[debut:fin] == "Awa Diouf"


def test_recadrage_retire_saut_de_ligne_et_espace_de_queue() -> None:
    from app.detection.ner import recadrer

    texte = "Objet :\nEcobank  suite"
    debut, fin, valeur = recadrer(texte, texte.index("\nEcobank"), texte.index("suite"))
    assert valeur == "Ecobank"
    assert texte[debut:fin] == "Ecobank"


def test_recadrage_borne_les_offsets_hors_limites() -> None:
    from app.detection.ner import recadrer

    assert recadrer("abc", -5, 99) == (0, 3, "abc")


def test_recadrage_empan_entierement_blanc() -> None:
    from app.detection.ner import recadrer

    debut, fin, valeur = recadrer("a   b", 1, 4)
    assert valeur == ""
    assert debut == fin
