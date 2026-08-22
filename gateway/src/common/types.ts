/**
 * Types du domaine — miroir exact des ENUM PostgreSQL.
 *
 * Nommage : domaine en français (cohérent avec le schéma SQL et le mémoire),
 * API techniques en anglais.
 */

export const NIVEAUX = ['faible', 'moyen', 'eleve', 'critique'] as const;
export type NiveauSens = (typeof NIVEAUX)[number];

export const ACTIONS = ['complet', 'masque', 'pseudonymise', 'refus'] as const;
export type ActionAcces = (typeof ACTIONS)[number];

export const STATUTS = ['decouvert', 'en_analyse', 'analyse', 'echec'] as const;
export type StatutDoc = (typeof STATUTS)[number];

export const TYPES_SOURCE = ['s3', 'gdrive', 'local'] as const;
export type TypeSource = (typeof TYPES_SOURCE)[number];

export type MethodeDetect = 'regle' | 'ner' | 'fusion';

/** Ordre total des niveaux, utilisé pour les comparaisons et les agrégats. */
export const ORDRE_NIVEAU: Record<NiveauSens, number> = {
  faible: 0,
  moyen: 1,
  eleve: 2,
  critique: 3,
};

export interface Source {
  id: string;
  type: TypeSource;
  libelle: string;
  configuration: Record<string, unknown>;
  frequenceCron: string;
  dernierScan: Date | null;
  actif: boolean;
}

export interface DocumentCatalogue {
  id: string;
  sourceId: string;
  cheminSource: string;
  empreinteSha256: string;
  typeMime: string | null;
  tailleOctets: number | null;
  statut: StatutDoc;
  niveauMax: NiveauSens | null;
  dateDecouverte: Date;
  dateAnalyse: Date | null;
  tentatives: number;
  motifEchec: string | null;
}

/** Entité telle qu'elle est persistée : jamais de valeur en clair. */
export interface EntitePersistee {
  typeEntite: string;
  empreinteValeur: string;
  positionDebut: number;
  positionFin: number;
  page: number | null;
  niveauSensibilite: NiveauSens;
  scoreConfiance: number | null;
  methode: MethodeDetect;
}

/** Entité telle qu'elle sort du moteur IA : contient la valeur. */
export interface EntiteAnalysee {
  typeEntite: string;
  valeur: string;
  debut: number;
  fin: number;
  page: number | null;
  niveau: NiveauSens;
  score: number;
  methode: MethodeDetect;
}

export interface UtilisateurJwt {
  sub: string;
  role: string;
}

export const ACTIONS_AUDIT = {
  LECTURE: 'LECTURE',
  REFUS: 'REFUS',
  SCAN: 'SCAN',
  CONFIG: 'CONFIG',
  AUTHENTIFICATION: 'AUTHENTIFICATION',
} as const;

export type ActionAudit = (typeof ACTIONS_AUDIT)[keyof typeof ACTIONS_AUDIT];
