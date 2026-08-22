"""Tolérance de la détection au texte océrisé.

Deux mécanismes, activés seulement quand le texte vient de l'OCR :

  1. réparation des jetons disloqués par des espaces parasites ;
  2. conservation des candidats dont une somme de contrôle échoue.

Le test qui compte le plus est celui du report d'offsets : la réparation crée un
texte de travail, et un empan trouvé dedans doit se retraduire **exactement**
dans le texte d'origine, sinon le masquage s'applique à côté (piège n°1).
"""

from __future__ import annotations

import pytest

from app.detection import rules
from app.detection.reparation_ocr import reparer, vaut_la_peine

IBAN_VALIDE = "SN91SN0100152000048500000765"
IBAN_ABIME = "SN91SN0100152000048500000766"   # dernier chiffre modifié : mod-97 échoue


def types_de(texte: str, ocr: bool = False) -> set[str]:
    return {e.typeEntite for e in rules.detecter(texte, ocr=ocr)}


def entites_de(texte: str, type_entite: str, ocr: bool = False) -> list:
    return [e for e in rules.detecter(texte, ocr=ocr) if e.typeEntite == type_entite]


# --- Réparation : texte et offsets -------------------------------------------


def test_recolle_une_adresse_electronique_disloquee() -> None:
    repare = reparer("courriel binetandiaye @mail .bj fin")
    assert "binetandiaye@mail.bj" in repare.texte


def test_recolle_une_date_disloquee() -> None:
    assert "03/07/1988" in reparer("ne le 03 / 07 / 1988 a Thies").texte


def test_recolle_une_plaque_disloquee() -> None:
    assert "DK-4521-AB" in reparer("vehicule DK - 4521 - AB immatricule").texte


def test_ne_touche_pas_a_la_ponctuation_de_phrase() -> None:
    """Deux-points et virgules portent la structure : les recoller n'aurait
    aucun intérêt et fabriquerait des jetons parasites."""
    texte = "Nom : Awa Diouf, domiciliee a Dakar"
    assert reparer(texte).texte == texte


def test_n_agit_pas_quand_les_deux_cotes_ne_sont_pas_alphanumeriques() -> None:
    texte = "fin . ( suite )"
    assert reparer(texte).texte == texte


def test_offsets_retraduits_exactement() -> None:
    """Le test central : l'empan trouvé dans le texte réparé doit désigner,
    dans le texte d'origine, la donnée entière — espaces parasites compris."""
    texte = "courriel binetandiaye @mail .bj fin"
    repare = reparer(texte)

    debut = repare.texte.index("binetandiaye@mail.bj")
    fin = debut + len("binetandiaye@mail.bj")
    debut_src, fin_src = repare.span_source(debut, fin)

    assert texte[debut_src:fin_src] == "binetandiaye @mail .bj"


def test_table_offsets_croissante_et_bornee() -> None:
    texte = "a @b .c 03 / 07 / 1988 et DK - 4521 - AB"
    repare = reparer(texte)

    assert len(repare.map_offsets) == len(repare.texte) + 1
    assert all(
        repare.map_offsets[i] <= repare.map_offsets[i + 1]
        for i in range(len(repare.map_offsets) - 1)
    )
    assert all(0 <= o <= len(texte) for o in repare.map_offsets)


def test_texte_sans_dislocation_est_rendu_intact() -> None:
    texte = "IBAN SN91SN0100152000048500000765 et awa@exemple.sn"
    assert reparer(texte).texte == texte
    assert vaut_la_peine(texte) is False


def test_vaut_la_peine_detecte_une_dislocation() -> None:
    assert vaut_la_peine("awa @exemple .sn") is True


def test_texte_vide() -> None:
    repare = reparer("")
    assert repare.texte == ""
    assert repare.map_offsets == [0]


# --- Effet sur la détection --------------------------------------------------


def test_courriel_disloque_detecte_seulement_en_mode_ocr() -> None:
    texte = "courriel binetandiaye @mail .bj"

    assert "EMAIL" not in types_de(texte, ocr=False)
    assert "EMAIL" in types_de(texte, ocr=True)


def test_l_empan_du_courriel_recouvre_toute_la_donnee() -> None:
    # Indispensable pour la protection : masquer seulement « binetandiaye »
    # laisserait le domaine lisible.
    texte = "courriel binetandiaye @mail .bj fin"
    entite = entites_de(texte, "EMAIL", ocr=True)[0]

    assert texte[entite.debut : entite.fin] == "binetandiaye @mail .bj"


def test_le_motif_de_date_tolerait_deja_les_espaces() -> None:
    """`MOTIF_DATE_NUM` admet `\\s*` autour des séparateurs : une date
    disloquée était déjà reconnue sans réparation. La réparation ne lui apporte
    donc rien, et ne doit rien lui retirer."""
    texte = "ne le 03 / 07 / 1988 a Thies"
    assert "DATE_NAISSANCE" in types_de(texte, ocr=False)
    assert "DATE_NAISSANCE" in types_de(texte, ocr=True)


# --- Sommes de contrôle en échec ---------------------------------------------


def test_iban_abime_conserve_en_mode_ocr() -> None:
    texte = f"RIB : {IBAN_ABIME}"

    assert "IBAN" not in types_de(texte, ocr=False)   # mod-97 rejette
    assert "IBAN" in types_de(texte, ocr=True)        # conservé, à score réduit


def test_iban_abime_reste_non_valide_mais_confiant() -> None:
    """`valide=False` — le mod-97 n'a pas confirmé — mais le score reste élevé.

    C'est la distinction utile : la validation dit « la somme de contrôle
    passe », le score dit « c'est probablement un IBAN ». Sur du texte océrisé
    les deux se dissocient, et confondre les deux faisait perdre la donnée à la
    fusion (voir `test_un_iban_ocerise_survit_a_une_etiquette_ner_concurrente`).
    """
    entite = entites_de(f"RIB : {IBAN_ABIME}", "IBAN", ocr=True)[0]

    assert entite.valide is False
    assert entite.score < 0.99          # en dessous d'une détection validée
    assert entite.score > 0.85          # au-dessus d'une étiquette NER générique


def test_iban_intact_reste_valide_et_prioritaire() -> None:
    entite = entites_de(f"RIB : {IBAN_VALIDE}", "IBAN", ocr=True)[0]

    assert entite.valide is True
    assert entite.score > 0.9


def test_carte_abimee_conservee_en_mode_ocr() -> None:
    texte = "Carte 4539 5787 6362 1487"   # Luhn échoue
    assert "CARTE_BANCAIRE" not in types_de(texte, ocr=False)
    assert "CARTE_BANCAIRE" in types_de(texte, ocr=True)


def test_date_impossible_reste_rejetee_meme_en_ocr() -> None:
    """La distinction assumée : une somme de contrôle est détruite par un
    caractère mal lu, un contrôle de plausibilité non. Le 32 d'un mois n'est
    pas une date de naissance abîmée, c'est autre chose."""
    texte = "Reference 32/13/1990"
    assert "DATE_NAISSANCE" not in types_de(texte, ocr=False)
    assert "DATE_NAISSANCE" not in types_de(texte, ocr=True)


# --- Non-régression sur le texte propre --------------------------------------


@pytest.mark.parametrize(
    "texte,attendu",
    [
        ("Contacter awa.diouf@exemple.sn", "EMAIL"),
        (f"RIB : {IBAN_VALIDE}", "IBAN"),
        ("Ne le 03/07/1988 a Thies", "DATE_NAISSANCE"),
        ("Tel +221 77 555 44 33", "TELEPHONE"),
        ("Carte 4539 5787 6362 1486", "CARTE_BANCAIRE"),
    ],
)
def test_le_texte_propre_donne_le_meme_resultat_dans_les_deux_modes(
    texte: str, attendu: str
) -> None:
    assert attendu in types_de(texte, ocr=False)
    assert attendu in types_de(texte, ocr=True)


def test_aucune_detection_supplementaire_sur_un_texte_sans_dcp() -> None:
    texte = "Le ciel est bleu et la procedure est close."
    assert rules.detecter(texte, ocr=True) == []


def test_le_mode_ocr_ne_duplique_pas_les_detections() -> None:
    """Sans dislocation, le second passage n'a pas lieu : une seule entité."""
    texte = "Contacter awa.diouf@exemple.sn pour la suite"
    assert len(entites_de(texte, "EMAIL", ocr=True)) == 1


def test_une_adresse_complete_ne_deborde_pas_sur_le_mot_suivant() -> None:
    """Régression : la réparation insérait un point après un domaine déjà
    pointé, et `awa.diouf@exemple.sn pour la suite` devenait
    `awa.diouf@exemple.sn.pour`. Le masquage débordait sur le texte courant."""
    texte = "Contacter awa.diouf@exemple.sn pour la suite"
    entite = entites_de(texte, "EMAIL", ocr=True)[0]

    assert entite.valeur == "awa.diouf@exemple.sn"
    assert texte[entite.debut : entite.fin] == "awa.diouf@exemple.sn"


# --- Point de domaine remplacé par un espace ---------------------------------


def test_restitue_le_point_du_domaine() -> None:
    """Cas mesuré sur le corpus : l'OCR ne décale pas le point, il le remplace
    par un espace. `mail.bj` ressort en `mall bJ`."""
    assert reparer("binetandiaye @mall bJ").texte == "binetandiaye@mall.bJ"


def test_courriel_sans_point_de_domaine_detecte_en_mode_ocr() -> None:
    texte = "Coumiel bienvenudossou@mail bj fin"

    assert "EMAIL" not in types_de(texte, ocr=False)
    assert "EMAIL" in types_de(texte, ocr=True)


def test_l_empan_couvre_le_domaine_entier() -> None:
    texte = "Coumiel bienvenudossou@mail bj fin"
    entite = entites_de(texte, "EMAIL", ocr=True)[0]
    assert texte[entite.debut : entite.fin] == "bienvenudossou@mail bj"


def test_n_invente_pas_de_point_hors_contexte_d_adresse() -> None:
    # Sans `@` devant, un espace entre deux mots reste un espace.
    texte = "la ville de Dakar au Senegal"
    assert reparer(texte).texte == texte


def test_n_invente_pas_de_point_devant_un_mot_trop_long() -> None:
    # `[A-Za-z]{2,4}` : une extension de domaine, pas un mot quelconque.
    assert reparer("awa@exemple domicile").texte == "awa@exemple domicile"


def test_offsets_composes_apres_deux_reparations() -> None:
    """Les deux mécanismes s'enchaînent : retrait d'espaces puis restitution du
    point. La table finale doit ramener au texte d'origine, pas au texte
    intermédiaire."""
    texte = "courriel binetandiaye @mall bJ fin"
    repare = reparer(texte)

    debut = repare.texte.index("binetandiaye@mall.bJ")
    fin = debut + len("binetandiaye@mall.bJ")
    debut_src, fin_src = repare.span_source(debut, fin)

    assert texte[debut_src:fin_src] == "binetandiaye @mall bJ"
    assert len(repare.map_offsets) == len(repare.texte) + 1


# --- Chiffres de contrôle lus comme des lettres ------------------------------


def test_iban_dont_la_cle_est_lue_comme_une_lettre() -> None:
    """`SN68…` ressort en `SNG8…` : le motif strict exige `\\d{2}` et ne
    correspond plus du tout. Sans motif tolérant, il n'y a même pas de candidat
    à soumettre au mod-97."""
    texte = "sur le compte SNG8SN0781618495931034131647."

    assert "IBAN" not in types_de(texte, ocr=False)
    assert "IBAN" in types_de(texte, ocr=True)


def test_iban_a_cle_confondue_est_conserve_sans_etre_valide() -> None:
    entite = entites_de("compte SNS3SN7242388496965328710122", "IBAN", ocr=True)[0]

    assert entite.valide is False
    assert entite.score < 0.99


def test_l_empan_de_l_iban_confondu_couvre_toute_la_valeur() -> None:
    texte = "compte SNG8SN0781618495931034131647 fin"
    entite = entites_de(texte, "IBAN", ocr=True)[0]
    assert texte[entite.debut : entite.fin] == "SNG8SN0781618495931034131647"


def test_le_motif_tolerant_ne_degrade_pas_l_iban_intact() -> None:
    entite = entites_de(f"RIB {IBAN_VALIDE}", "IBAN", ocr=True)[0]
    assert entite.valide is True
    assert entite.score > 0.9


def test_le_motif_tolerant_n_est_pas_utilise_sur_texte_propre() -> None:
    # Une référence quelconque commençant par quatre lettres ne doit pas devenir
    # un IBAN hors contexte OCR.
    assert "IBAN" not in types_de("code ABCDEFGHIJKLMNOP0123456789", ocr=False)


# --- Interaction avec la fusion ----------------------------------------------


def test_un_iban_ocerise_survit_a_une_etiquette_ner_concurrente() -> None:
    """Régression mesurée sur le corpus.

    spaCy étiquette volontiers une longue chaîne alphanumérique en
    `ORGANISATION` ou `LOCALITE`, avec un score constant de 0,85. Quand le
    candidat IBAN portait un score de 0,45, la fusion — qui départage à empan
    égal par le score — faisait gagner l'étiquette NER. L'IBAN n'était pas
    seulement manqué : il était **remplacé**, donc reclassé de `critique` à
    `faible`. C'est un sous-classement, la faille que M5 interdit.
    """
    from app.classification import sensitivity
    from app.detection import merge
    from app.models import Entite, MethodeDetect, NiveauSens

    texte = "sur le compte SNG8SN0781618495931034131647 fin"
    candidats = rules.detecter(texte, ocr=True)
    iban = next(e for e in candidats if e.typeEntite == "IBAN")

    # L'étiquette NER concurrente, sur exactement le même empan.
    concurrent = Entite(
        typeEntite="ORGANISATION",
        valeur=texte[iban.debut : iban.fin],
        debut=iban.debut,
        fin=iban.fin,
        score=0.85,
        methode=MethodeDetect.ner,
    )

    retenues = sensitivity.classer(merge.fusionner([*candidats, concurrent]))
    survivant = next(e for e in retenues if e.debut < iban.fin and iban.debut < e.fin)

    assert survivant.typeEntite == "IBAN"
    assert survivant.niveau == NiveauSens.critique


def test_le_score_ocr_depasse_la_constante_ner() -> None:
    # Verrouille la relation d'ordre dont dépend le test précédent.
    from app.detection.ner import MoteurSpacy  # noqa: F401  (documente la source)

    regle_iban = next(r for r in rules.REGLES if r.type_entite == "IBAN")
    assert regle_iban.score_ocr_non_valide > 0.85
    assert regle_iban.score_ocr_non_valide < regle_iban.score_valide


def test_un_numero_etiquete_cni_prime_sur_une_coincidence_de_luhn() -> None:
    """Un NIN de 13 chiffres satisfait parfois Luhn par coïncidence.

    `CARTE_BANCAIRE` l'emportait alors à la fusion. Les deux types étant
    `critique`, la donnée restait protégée — aucune fuite — mais le document
    était décrit comme portant un numéro de carte. L'étiquette explicite du
    document tranche : « N° CNI : » est une preuve plus forte qu'un format qui
    tombe juste.
    """
    from app.classification import sensitivity
    from app.detection import merge
    from app.models import NiveauSens

    texte = "Titulaire de la carte nationale, N° CNI : 4828148932528, delivree a Dakar"
    retenues = sensitivity.classer(merge.fusionner(rules.detecter(texte, ocr=True)))
    sur_le_numero = [e for e in retenues if "4828148932528" in e.valeur]

    assert sur_le_numero, "le numéro doit être détecté"
    assert sur_le_numero[0].typeEntite == "NUM_PIECE_IDENTITE"
    assert sur_le_numero[0].niveau == NiveauSens.critique


def test_sans_etiquette_l_ambiguite_n_est_pas_tranchee_artificiellement() -> None:
    # Un numéro nu de 13 chiffres valide au sens de Luhn reste ambigu : on ne
    # force pas le type pour flatter une métrique. Le niveau `critique` — seul
    # élément qui commande la politique — est le même dans les deux cas.
    from app.classification import sensitivity
    from app.detection import merge
    from app.models import NiveauSens

    texte = "Reference de dossier 4828148932528 traitee ce jour"
    retenues = sensitivity.classer(merge.fusionner(rules.detecter(texte, ocr=True)))
    sur_le_numero = [e for e in retenues if "4828148932528" in e.valeur]

    assert sur_le_numero
    assert sur_le_numero[0].niveau == NiveauSens.critique


# --- Extension de domaine rognée ---------------------------------------------


def test_courriel_a_extension_rognee_detecte_en_mode_ocr() -> None:
    """`poste.ci` ressort en `poste.c` : le dernier caractère de la page est
    régulièrement rogné. Le motif strict exige deux caractères d'extension et
    perd alors toute l'adresse."""
    texte = "adressee a moussa.bamba@poste.c sous cinq jours"

    assert "EMAIL" not in types_de(texte, ocr=False)
    assert "EMAIL" in types_de(texte, ocr=True)


def test_courriel_a_extension_bruitee() -> None:
    texte = "Coumiel bienvenudossou@mail.b]"
    entite = entites_de(texte, "EMAIL", ocr=True)[0]
    assert entite.valeur == "bienvenudossou@mail.b"


def test_la_relaxation_n_invente_pas_d_adresse_sans_arobase() -> None:
    assert "EMAIL" not in types_de("le fichier rapport.p contient tout", ocr=True)


def test_l_extension_a_deux_caracteres_reste_detectee_sur_texte_propre() -> None:
    for mode in (False, True):
        assert "EMAIL" in types_de("awa.diouf@exemple.sn", ocr=mode)


def test_domaine_avec_caractere_parasite() -> None:
    """L'OCR insère des caractères dans le domaine : `poste` -> `pos'e`.
    Les énumérer serait sans fin ; on admet tout caractère non blanc, la
    structure `@…point…extension` restant très contraignante."""
    texte = "adresse komlan_diouf@pos'e.ci fin"

    assert "EMAIL" not in types_de(texte, ocr=False)
    assert "EMAIL" in types_de(texte, ocr=True)


def test_domaine_cumulant_caractere_parasite_et_point_manquant() -> None:
    texte = "question : aminata_kouadio@pos'e ci"
    assert "EMAIL" in types_de(texte, ocr=True)


def test_une_mention_peut_produire_un_faux_positif_et_c_est_assume() -> None:
    """Compromis explicite, en mode OCR uniquement.

    Recoller l'espace devant un `@` est nécessaire — `binetandiaye @mall bJ` en
    dépend — mais fait aussi de `voir @twitter le` une adresse. Le coût est un
    masquage superflu de deux mots ; le gain est de ne pas laisser une adresse
    en clair. C'est exactement l'asymétrie que le F2 arbitre, et le document
    reste protégé plutôt que fuité.

    Sur texte propre, aucun de ces deux comportements n'existe.
    """
    assert "EMAIL" not in types_de("voir @twitter le matin", ocr=False)
    assert "EMAIL" in types_de("voir @twitter le matin", ocr=True)
