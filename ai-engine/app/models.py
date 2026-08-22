"""Schémas Pydantic partagés — frontière d'API du moteur IA.

Nommage : domaine en français (aligné sur le mémoire et sur le schéma SQL),
structures techniques en anglais.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class NiveauSens(str, Enum):
    faible = "faible"
    moyen = "moyen"
    eleve = "eleve"
    critique = "critique"


ORDRE_NIVEAU: dict[str, int] = {
    NiveauSens.faible: 0,
    NiveauSens.moyen: 1,
    NiveauSens.eleve: 2,
    NiveauSens.critique: 3,
}


def niveau_max(niveaux: list[str]) -> str | None:
    """Maximum d'une liste de niveaux, ou None si la liste est vide."""
    if not niveaux:
        return None
    return max(niveaux, key=lambda n: ORDRE_NIVEAU.get(n, -1))


class MethodeDetect(str, Enum):
    regle = "regle"
    ner = "ner"
    fusion = "fusion"


class MethodeExtraction(str, Enum):
    pdf = "pdf"
    docx = "docx"
    plain = "plain"
    ocr = "ocr"
    aucune = "aucune"


class ActionProtection(str, Enum):
    masque = "masque"
    pseudonymise = "pseudonymise"


class Entite(BaseModel):
    """Une donnée personnelle localisée dans le texte normalisé."""

    typeEntite: str
    valeur: str
    debut: int
    fin: int
    page: int | None = None
    niveau: NiveauSens = NiveauSens.moyen
    score: float = 1.0
    methode: MethodeDetect = MethodeDetect.regle
    # True lorsqu'un validateur structurel (mod-97, Luhn, plage de dates…)
    # a confirmé la détection. Utilisé en priorité 1 par la fusion.
    valide: bool = False

    @property
    def longueur(self) -> int:
        return self.fin - self.debut


class RequeteAnalyse(BaseModel):
    documentId: str
    typeMime: str | None = None
    contenuBase64: str
    nomFichier: str | None = None


class ReponseAnalyse(BaseModel):
    texteExtrait: bool
    methodeExtraction: MethodeExtraction
    cerEstime: float | None = None
    entites: list[Entite] = Field(default_factory=list)
    niveauMax: NiveauSens | None = None
    nbCaracteres: int = 0
    nbPages: int | None = None


class RequeteProtection(BaseModel):
    documentId: str
    typeMime: str | None = None
    contenuBase64: str
    action: ActionProtection
    niveauSeuil: NiveauSens = NiveauSens.moyen
    nomFichier: str | None = None


class ReponseProtection(BaseModel):
    contenuBase64: str
    nbEntitesProtegees: int
    typeMimeSortie: str


class ReponseSante(BaseModel):
    statut: str
    modeleNer: str
    versionTesseract: str
