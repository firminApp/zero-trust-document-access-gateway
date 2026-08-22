"""Génération du corpus synthétique annoté.

L'avantage décisif du synthétique : l'annotation est **produite en même temps
que le document**. La vérité terrain est donc exacte, pas estimée par un
annotateur — ce qui élimine la principale source de bruit des évaluations de
dé-identification.

Partition **au niveau du document** (70/15/15). Jamais au niveau de l'entité :
sinon une entité du jeu de test aurait pu être vue à l'entraînement, et les
scores rapportés seraient optimistes.

    python corpus/generate.py --nombre 200 --sortie corpus/data/synthetic
"""

from __future__ import annotations

import argparse
import json
import random
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

# --- Listes régionales -------------------------------------------------------
# Faker fr_FR ne produit que des patronymes hexagonaux. Le corpus doit refléter
# la population réelle des plateformes visées (Acte additionnel CEDEAO).

PRENOMS_OUEST = [
    "Awa", "Fatou", "Aminata", "Mariama", "Khady", "Ndeye", "Adama", "Bineta",
    "Mamadou", "Ousmane", "Ibrahima", "Cheikh", "Modou", "Moussa", "Abdoulaye",
    "Kofi", "Kwame", "Yao", "Koffi", "Komlan", "Afi", "Akossiwa", "Eyram",
    "Bienvenu", "Rachidatou", "Wassiou", "Nadège", "Sègbédji", "Fadilou",
    "Aya", "Konan", "Adjoua", "N'Guessan", "Kouassi", "Affoué",
]

NOMS_OUEST = [
    "Diouf", "Ndiaye", "Fall", "Sow", "Sarr", "Gueye", "Diop", "Faye", "Ba",
    "Cissé", "Camara", "Traoré", "Keita", "Coulibaly", "Sylla",
    "Mensah", "Owusu", "Boateng", "Asante", "Agyeman",
    "Adjovi", "Hounkpatin", "Dossou", "Zinsou", "Gbaguidi", "Ahouandjinou",
    "Amegan", "Kodjo", "Lawson", "Agbeko",
    "Kouamé", "Yao", "N'Dri", "Kouadio", "Bamba",
]

VILLES = [
    ("Dakar", "SN", "+221"), ("Thiès", "SN", "+221"), ("Saint-Louis", "SN", "+221"),
    ("Ziguinchor", "SN", "+221"), ("Touba", "SN", "+221"),
    ("Cotonou", "BJ", "+229"), ("Porto-Novo", "BJ", "+229"), ("Parakou", "BJ", "+229"),
    ("Lomé", "TG", "+228"), ("Sokodé", "TG", "+228"), ("Kara", "TG", "+228"),
    ("Abidjan", "CI", "+225"), ("Bouaké", "CI", "+225"), ("Yamoussoukro", "CI", "+225"),
    ("Accra", "GH", "+233"), ("Kumasi", "GH", "+233"),
]

VOIES = [
    "rue", "avenue", "boulevard", "route", "impasse", "allée",
]

QUARTIERS = [
    "Sicap Liberté", "Grand Yoff", "Médina", "Point E", "Almadies", "Ouakam",
    "Fidjrossè", "Cadjèhoun", "Akpakpa", "Zogbo",
    "Bè", "Tokoin", "Adidogomé",
    "Cocody", "Yopougon", "Marcory", "Treichville",
]

ORGANISATIONS = [
    "Gozem", "Sonatel", "Orange Money", "Ecobank", "UBA", "Bank of Africa",
    "Wave", "MTN", "Moov Africa", "Coris Bank", "NSIA", "Sunu Assurances",
]

TYPES_DOCUMENT = (
    "attestation",
    "contrat",
    "formulaire_enrolement",
    "courrier",
    "piece_identite",
    "releve_bancaire",
    "note_service",       # niveau faible
    "accuse_reception",   # niveau moyen
)


# --- Structures --------------------------------------------------------------


@dataclass
class AnnotationEntite:
    type: str
    valeur: str
    debut: int
    fin: int
    niveau: str


@dataclass
class DocumentAnnote:
    id: str
    chemin: str
    typeDocument: str
    partition: str
    texte: str
    entites: list[AnnotationEntite] = field(default_factory=list)


class Redacteur:
    """Assemble un texte en enregistrant la position exacte de chaque entité.

    C'est le cœur du générateur : `ajouter_entite` écrit et annote dans la même
    opération, ce qui rend impossible une annotation décalée.
    """

    def __init__(self) -> None:
        self._morceaux: list[str] = []
        self._longueur = 0
        self.entites: list[AnnotationEntite] = []

    def ecrire(self, texte: str) -> None:
        self._morceaux.append(texte)
        self._longueur += len(texte)

    def ajouter_entite(self, type_entite: str, valeur: str, niveau: str) -> None:
        debut = self._longueur
        self.ecrire(valeur)
        self.entites.append(
            AnnotationEntite(
                type=type_entite, valeur=valeur, debut=debut, fin=self._longueur, niveau=niveau
            )
        )

    @property
    def texte(self) -> str:
        return "".join(self._morceaux)

    def verifier(self) -> None:
        """Contrôle que chaque annotation retombe bien sur sa valeur."""
        texte = self.texte
        for entite in self.entites:
            extrait = texte[entite.debut : entite.fin]
            if extrait != entite.valeur:
                raise AssertionError(
                    f"Annotation décalée : attendu {entite.valeur!r}, trouvé {extrait!r}"
                )


# --- Fabrique de valeurs -----------------------------------------------------


class Fabrique:
    def __init__(self, graine: int) -> None:
        self.alea = random.Random(graine)
        self.faker = Faker("fr_FR")
        Faker.seed(graine)

    def personne(self) -> tuple[str, str]:
        prenom = self.alea.choice(PRENOMS_OUEST)
        nom = self.alea.choice(NOMS_OUEST)
        return prenom, nom

    def ville(self) -> tuple[str, str, str]:
        return self.alea.choice(VILLES)

    def telephone(self, indicatif: str) -> str:
        longueurs = {"+221": 9, "+229": 8, "+228": 8, "+225": 10, "+233": 9}
        nb = longueurs.get(indicatif, 9)
        prefixes = {
            "+221": ("70", "76", "77", "78"),
            "+229": ("97", "96", "95", "66"),
            "+228": ("90", "91", "92", "99"),
            "+225": ("07", "05", "01"),
            "+233": ("24", "54", "55"),
        }
        tete = self.alea.choice(prefixes.get(indicatif, ("77",)))
        reste = "".join(str(self.alea.randint(0, 9)) for _ in range(nb - len(tete)))
        chiffres = tete + reste
        groupes = [chiffres[i : i + 2] for i in range(0, len(chiffres), 2)]
        return f"{indicatif} {' '.join(groupes)}"

    def email(self, prenom: str, nom: str) -> str:
        def sans_accent(texte: str) -> str:
            decompose = unicodedata.normalize("NFKD", texte)
            return "".join(c for c in decompose if not unicodedata.combining(c))

        domaine = self.alea.choice(["exemple.sn", "mail.bj", "courriel.tg", "poste.ci"])
        separateur = self.alea.choice([".", "_", ""])
        base = f"{sans_accent(prenom).lower()}{separateur}{sans_accent(nom).lower()}"
        return f"{base.replace(' ', '').replace(chr(39), '')}@{domaine}"

    def date_naissance(self) -> str:
        naissance = date(1960, 1, 1) + timedelta(days=self.alea.randint(0, 365 * 45))
        gabarit = self.alea.choice(["%d/%m/%Y", "%d-%m-%Y", "textuel"])
        if gabarit == "textuel":
            mois = [
                "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                "août", "septembre", "octobre", "novembre", "décembre",
            ]
            return f"{naissance.day} {mois[naissance.month - 1]} {naissance.year}"
        return naissance.strftime(gabarit)

    def iban(self, pays: str = "SN") -> str:
        """IBAN à clé mod-97 correcte : un IBAN invalide serait rejeté par le
        validateur et fausserait le rappel mesuré."""
        bban = "".join(str(self.alea.randint(0, 9)) for _ in range(22))
        bban = f"SN{bban[:22]}" if pays == "SN" else bban
        provisoire = f"{bban}{pays}00"
        numerique = "".join(
            str(ord(c) - 55) if c.isalpha() else c for c in provisoire
        )
        reste = 0
        for chiffre in numerique:
            reste = (reste * 10 + int(chiffre)) % 97
        cle = 98 - reste
        return f"{pays}{cle:02d}{bban}"

    def carte_bancaire(self) -> str:
        """Numéro valide au sens de Luhn (préfixe de test 4539)."""
        base = "4539" + "".join(str(self.alea.randint(0, 9)) for _ in range(11))
        total = 0
        for index, caractere in enumerate(reversed(base)):
            chiffre = int(caractere)
            if index % 2 == 0:
                chiffre *= 2
                if chiffre > 9:
                    chiffre -= 9
            total += chiffre
        controle = (10 - total % 10) % 10
        numero = base + str(controle)
        return " ".join(numero[i : i + 4] for i in range(0, 16, 4))

    def piece_identite(self, pays: str) -> str:
        if pays == "SN":
            return f"{self.alea.choice('12')}{''.join(str(self.alea.randint(0, 9)) for _ in range(12))}"
        if pays == "BJ":
            return "".join(str(self.alea.randint(0, 9)) for _ in range(10))
        return "".join(str(self.alea.randint(0, 9)) for _ in range(13))

    def adresse(self, ville: str) -> str:
        return (
            f"{self.alea.randint(1, 250)} {self.alea.choice(VOIES)} "
            f"{self.alea.choice(QUARTIERS)}, {ville}"
        )

    def plaque(self) -> str:
        lettres = "".join(self.alea.choice("ABCDEFGHJKLMNPRSTVWXYZ") for _ in range(2))
        suffixe = "".join(self.alea.choice("ABCDEFGHJKLMNPRSTVWXYZ") for _ in range(2))
        return f"{lettres}-{self.alea.randint(1000, 9999)}-{suffixe}"


# --- Gabarits de document ----------------------------------------------------


def _identite(redacteur: Redacteur, fabrique: Fabrique) -> dict[str, str]:
    prenom, nom = fabrique.personne()
    ville, pays, indicatif = fabrique.ville()
    return {
        "prenom": prenom,
        "nom": nom,
        "complet": f"{prenom} {nom}",
        "ville": ville,
        "pays": pays,
        "indicatif": indicatif,
    }


def gabarit_attestation(redacteur: Redacteur, fabrique: Fabrique) -> None:
    ident = _identite(redacteur, fabrique)

    redacteur.ecrire("ATTESTATION DE DOMICILE\n\n")
    redacteur.ecrire("Je soussigné(e) ")
    redacteur.ajouter_entite("NOM_PERSONNE", ident["complet"], "moyen")
    redacteur.ecrire(", né(e) le ")
    redacteur.ajouter_entite("DATE_NAISSANCE", fabrique.date_naissance(), "eleve")
    redacteur.ecrire(" à ")
    redacteur.ajouter_entite("LOCALITE", ident["ville"], "faible")
    redacteur.ecrire(",\ndemeurant ")
    redacteur.ajouter_entite("ADRESSE_POSTALE", fabrique.adresse(ident["ville"]), "moyen")
    redacteur.ecrire(",\natteste sur l'honneur résider à cette adresse.\n\n")
    redacteur.ecrire("Contact : ")
    redacteur.ajouter_entite("TELEPHONE", fabrique.telephone(ident["indicatif"]), "eleve")
    redacteur.ecrire(" — ")
    redacteur.ajouter_entite("EMAIL", fabrique.email(ident["prenom"], ident["nom"]), "moyen")
    redacteur.ecrire("\n\nFait à ")
    redacteur.ajouter_entite("LOCALITE", ident["ville"], "faible")
    redacteur.ecrire(", le 12/03/2026.\n")


def gabarit_contrat(redacteur: Redacteur, fabrique: Fabrique) -> None:
    ident = _identite(redacteur, fabrique)
    organisation = fabrique.alea.choice(ORGANISATIONS)

    redacteur.ecrire("CONTRAT DE PRESTATION DE SERVICE\n\nEntre les soussignés :\n\n")
    redacteur.ecrire("La société ")
    redacteur.ajouter_entite("ORGANISATION", organisation, "faible")
    redacteur.ecrire(", dont le siège est à ")
    redacteur.ajouter_entite("LOCALITE", ident["ville"], "faible")
    redacteur.ecrire(",\nci-après « le Prestataire »,\n\nEt ")
    redacteur.ajouter_entite("NOM_PERSONNE", ident["complet"], "moyen")
    redacteur.ecrire(", né(e) le ")
    redacteur.ajouter_entite("DATE_NAISSANCE", fabrique.date_naissance(), "eleve")
    redacteur.ecrire(",\ntitulaire de la pièce d'identité n° ")
    redacteur.ajouter_entite("NUM_PIECE_IDENTITE", fabrique.piece_identite(ident["pays"]), "critique")
    redacteur.ecrire(",\ndemeurant ")
    redacteur.ajouter_entite("ADRESSE_POSTALE", fabrique.adresse(ident["ville"]), "moyen")
    redacteur.ecrire(",\nci-après « le Client ».\n\n")
    redacteur.ecrire("Article 4 — Règlement\nLes règlements sont effectués sur le compte ")
    redacteur.ajouter_entite("IBAN", fabrique.iban(), "critique")
    redacteur.ecrire(".\nToute question : ")
    redacteur.ajouter_entite("EMAIL", fabrique.email(ident["prenom"], ident["nom"]), "moyen")
    redacteur.ecrire("\n")


def gabarit_formulaire(redacteur: Redacteur, fabrique: Fabrique) -> None:
    ident = _identite(redacteur, fabrique)

    redacteur.ecrire("FORMULAIRE D'ENRÔLEMENT CHAUFFEUR\n\n")
    redacteur.ecrire("Nom et prénom .......... ")
    redacteur.ajouter_entite("NOM_PERSONNE", ident["complet"], "moyen")
    redacteur.ecrire("\nDate de naissance ...... ")
    redacteur.ajouter_entite("DATE_NAISSANCE", fabrique.date_naissance(), "eleve")
    redacteur.ecrire("\nLieu de naissance ...... ")
    redacteur.ajouter_entite("LOCALITE", ident["ville"], "faible")
    redacteur.ecrire("\nN° pièce d'identité .... ")
    redacteur.ajouter_entite("NUM_PIECE_IDENTITE", fabrique.piece_identite(ident["pays"]), "critique")
    redacteur.ecrire("\nAdresse ................ ")
    redacteur.ajouter_entite("ADRESSE_POSTALE", fabrique.adresse(ident["ville"]), "moyen")
    redacteur.ecrire("\nTéléphone .............. ")
    redacteur.ajouter_entite("TELEPHONE", fabrique.telephone(ident["indicatif"]), "eleve")
    redacteur.ecrire("\nCourriel ............... ")
    redacteur.ajouter_entite("EMAIL", fabrique.email(ident["prenom"], ident["nom"]), "moyen")
    redacteur.ecrire("\nImmatriculation ........ ")
    redacteur.ajouter_entite("PLAQUE_IMMAT", fabrique.plaque(), "eleve")
    redacteur.ecrire("\nCompte de versement .... ")
    redacteur.ajouter_entite("IBAN", fabrique.iban(), "critique")
    redacteur.ecrire("\n\nSignature du candidat : ______________________\n")


def gabarit_courrier(redacteur: Redacteur, fabrique: Fabrique) -> None:
    ident = _identite(redacteur, fabrique)
    organisation = fabrique.alea.choice(ORGANISATIONS)

    redacteur.ajouter_entite("ORGANISATION", organisation, "faible")
    redacteur.ecrire("\nService clientèle\n")
    redacteur.ajouter_entite("LOCALITE", ident["ville"], "faible")
    redacteur.ecrire("\n\nObjet : réclamation dossier n° ")
    redacteur.ajouter_entite(
        "NUM_CLIENT", f"GZ-{fabrique.alea.randint(100000, 999999)}", "eleve"
    )
    redacteur.ecrire("\n\nMadame, Monsieur,\n\nJe fais suite à votre courrier concernant ")
    redacteur.ajouter_entite("NOM_PERSONNE", ident["complet"], "moyen")
    redacteur.ecrire(", joignable au ")
    redacteur.ajouter_entite("TELEPHONE", fabrique.telephone(ident["indicatif"]), "eleve")
    redacteur.ecrire(".\nLe remboursement peut être adressé à ")
    redacteur.ajouter_entite("EMAIL", fabrique.email(ident["prenom"], ident["nom"]), "moyen")
    redacteur.ecrire(".\n\nVeuillez agréer mes salutations distinguées.\n")


def gabarit_piece_identite(redacteur: Redacteur, fabrique: Fabrique) -> None:
    ident = _identite(redacteur, fabrique)

    redacteur.ecrire("RÉPUBLIQUE — CARTE NATIONALE D'IDENTITÉ\n\n")
    redacteur.ecrire("NOM : ")
    redacteur.ajouter_entite("NOM_PERSONNE", ident["nom"].upper(), "moyen")
    redacteur.ecrire("\nPRÉNOM : ")
    redacteur.ajouter_entite("NOM_PERSONNE", ident["prenom"], "moyen")
    redacteur.ecrire("\nNÉ(E) LE : ")
    redacteur.ajouter_entite("DATE_NAISSANCE", fabrique.date_naissance(), "eleve")
    redacteur.ecrire("\nÀ : ")
    redacteur.ajouter_entite("LOCALITE", ident["ville"], "faible")
    redacteur.ecrire("\nN° CNI : ")
    redacteur.ajouter_entite("NUM_PIECE_IDENTITE", fabrique.piece_identite(ident["pays"]), "critique")
    redacteur.ecrire("\nDOMICILE : ")
    redacteur.ajouter_entite("ADRESSE_POSTALE", fabrique.adresse(ident["ville"]), "moyen")
    redacteur.ecrire("\n")


def gabarit_releve(redacteur: Redacteur, fabrique: Fabrique) -> None:
    ident = _identite(redacteur, fabrique)

    redacteur.ecrire("RELEVÉ DE COMPTE — ")
    redacteur.ajouter_entite("ORGANISATION", fabrique.alea.choice(ORGANISATIONS), "faible")
    redacteur.ecrire("\n\nTitulaire : ")
    redacteur.ajouter_entite("NOM_PERSONNE", ident["complet"], "moyen")
    redacteur.ecrire("\nAdresse   : ")
    redacteur.ajouter_entite("ADRESSE_POSTALE", fabrique.adresse(ident["ville"]), "moyen")
    redacteur.ecrire("\nIBAN      : ")
    redacteur.ajouter_entite("IBAN", fabrique.iban(), "critique")
    redacteur.ecrire("\nCarte     : ")
    redacteur.ajouter_entite("CARTE_BANCAIRE", fabrique.carte_bancaire(), "critique")
    redacteur.ecrire("\n\nDate       Libellé                     Montant\n")
    for _ in range(fabrique.alea.randint(3, 7)):
        jour = fabrique.alea.randint(1, 28)
        montant = fabrique.alea.randint(500, 250000)
        redacteur.ecrire(
            f"{jour:02d}/02/26  Paiement course              {montant:>8} FCFA\n"
        )


def gabarit_note_service(redacteur: Redacteur, fabrique: Fabrique) -> None:
    """Document de niveau `faible` : ni personne nommée, ni identifiant.

    Le corpus doit contenir des documents de chaque niveau, sinon la matrice de
    politique n'est jamais exercée que sur ses lignes hautes et les cases
    `faible` / `moyen` restent des angles morts à la démonstration.
    """
    ident = _identite(redacteur, fabrique)

    redacteur.ecrire("NOTE DE SERVICE\n\n")
    redacteur.ecrire("À l'attention des équipes de ")
    redacteur.ajouter_entite("ORGANISATION", fabrique.alea.choice(ORGANISATIONS), "faible")
    redacteur.ecrire(" — agence de ")
    redacteur.ajouter_entite("LOCALITE", ident["ville"], "faible")
    redacteur.ecrire(".\n\nObjet : horaires du service clientèle\n\n")
    redacteur.ecrire(
        "Le guichet sera ouvert de 8h à 17h du lundi au vendredi.\n"
        "Les demandes reçues après 16h seront traitées le jour ouvré suivant.\n"
        "Aucune pièce justificative n'est à fournir pour cette démarche.\n\n"
    )
    redacteur.ecrire("La direction régionale de ")
    redacteur.ajouter_entite("LOCALITE", fabrique.ville()[0], "faible")
    redacteur.ecrire("\n")


def gabarit_accuse_reception(redacteur: Redacteur, fabrique: Fabrique) -> None:
    """Document de niveau `moyen` : une personne nommée et un courriel.

    Un seul identifiant de contact accompagne le nom : l'ajustement contextuel
    de M5 exige deux co-occurrences pour élever le nom, le document reste donc
    bien au niveau `moyen`.
    """
    ident = _identite(redacteur, fabrique)

    redacteur.ecrire("ACCUSÉ DE RÉCEPTION\n\n")
    redacteur.ajouter_entite("ORGANISATION", fabrique.alea.choice(ORGANISATIONS), "faible")
    redacteur.ecrire(" confirme la bonne réception de la demande de ")
    redacteur.ajouter_entite("NOM_PERSONNE", ident["complet"], "moyen")
    redacteur.ecrire(".\n\nUne réponse sera adressée à ")
    redacteur.ajouter_entite("EMAIL", fabrique.email(ident["prenom"], ident["nom"]), "moyen")
    redacteur.ecrire(" sous cinq jours ouvrés.\n\n")
    redacteur.ecrire("Agence de ")
    redacteur.ajouter_entite("LOCALITE", ident["ville"], "faible")
    redacteur.ecrire("\n")


GABARITS = {
    "attestation": gabarit_attestation,
    "contrat": gabarit_contrat,
    "formulaire_enrolement": gabarit_formulaire,
    "courrier": gabarit_courrier,
    "piece_identite": gabarit_piece_identite,
    "releve_bancaire": gabarit_releve,
    "note_service": gabarit_note_service,
    "accuse_reception": gabarit_accuse_reception,
}


# --- Génération --------------------------------------------------------------


def partition_de(index: int, total: int) -> str:
    """Partition 70/15/15 **au niveau du document**."""
    position = index / max(1, total)
    if position < 0.70:
        return "entrainement"
    if position < 0.85:
        return "validation"
    return "test"


def generer(nombre: int, sortie: Path, graine: int, formats: list[str]) -> list[DocumentAnnote]:
    sortie.mkdir(parents=True, exist_ok=True)
    fabrique = Fabrique(graine)
    documents: list[DocumentAnnote] = []

    for index in range(nombre):
        type_document = TYPES_DOCUMENT[index % len(TYPES_DOCUMENT)]
        redacteur = Redacteur()
        GABARITS[type_document](redacteur, fabrique)
        redacteur.verifier()

        identifiant = f"doc_{index:05d}"
        format_fichier = formats[index % len(formats)]
        chemin = sortie / f"{identifiant}.{format_fichier}"
        _ecrire_fichier(chemin, redacteur.texte, format_fichier)

        documents.append(
            DocumentAnnote(
                id=identifiant,
                chemin=str(chemin),
                typeDocument=type_document,
                partition=partition_de(index, nombre),
                texte=redacteur.texte,
                entites=redacteur.entites,
            )
        )

    # La vérité terrain est écrite À CÔTÉ du répertoire scanné, jamais dedans :
    # une source de stockage ne contient que des documents. Laisser le fichier
    # d'annotations parmi eux le ferait cataloguer, analyser, et échouer — un
    # artefact de démonstration qui n'apprend rien sur le système.
    annotations = sortie.parent / "annotations.jsonl"
    with annotations.open("w", encoding="utf-8") as flux:
        for document in documents:
            flux.write(json.dumps(asdict(document), ensure_ascii=False) + "\n")

    print(f"{len(documents)} documents générés dans {sortie}")
    print(f"Annotations : {annotations}")
    return documents


def _ecrire_fichier(chemin: Path, texte: str, format_fichier: str) -> None:
    if format_fichier == "txt":
        chemin.write_text(texte, encoding="utf-8")
    elif format_fichier == "pdf":
        _ecrire_pdf(chemin, texte)
    elif format_fichier == "docx":
        _ecrire_docx(chemin, texte)
    else:
        raise ValueError(f"Format inconnu : {format_fichier}")


def _ecrire_pdf(chemin: Path, texte: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    dessin = canvas.Canvas(str(chemin), pagesize=A4)
    dessin.setFont("Helvetica", 10.5)
    _, hauteur = A4
    y = hauteur - 60
    for ligne in texte.split("\n"):
        if y < 60:
            dessin.showPage()
            dessin.setFont("Helvetica", 10.5)
            y = hauteur - 60
        dessin.drawString(50, y, ligne)
        y -= 15
    dessin.save()


def _ecrire_docx(chemin: Path, texte: str) -> None:
    from docx import Document

    document = Document()
    for ligne in texte.split("\n"):
        document.add_paragraph(ligne)
    document.save(str(chemin))


def principal() -> None:
    analyseur = argparse.ArgumentParser(description="Génère le corpus synthétique annoté")
    analyseur.add_argument("--nombre", type=int, default=200)
    analyseur.add_argument("--sortie", type=Path, default=Path("corpus/data/synthetic"))
    analyseur.add_argument("--graine", type=int, default=42)
    analyseur.add_argument(
        "--formats",
        default="txt,pdf,docx",
        help="formats produits, en rotation (txt, pdf, docx)",
    )
    arguments = analyseur.parse_args()

    generer(
        arguments.nombre,
        arguments.sortie,
        arguments.graine,
        [f.strip() for f in arguments.formats.split(",") if f.strip()],
    )


if __name__ == "__main__":
    principal()
