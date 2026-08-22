/**
 * Contrat commun aux sources de stockage (M3).
 *
 * `lister()` est un **générateur asynchrone**, pas une promesse de tableau :
 * un bucket peut contenir des centaines de milliers d'objets, et le scan doit
 * pouvoir en traiter un lot pendant que la page suivante se charge, sans
 * jamais tenir l'inventaire complet en mémoire (piège n°3).
 */

export interface Ressource {
  cle: string;
  taille: number;
  dateModification: Date;
  typeMime?: string;
}

export interface Connecteur {
  lister(prefixe?: string): AsyncIterable<Ressource>;
  lire(cle: string): Promise<Buffer>;
  ecrire(cle: string, contenu: Buffer): Promise<void>;
}

/** Levée quand la source est joignable mais la ressource absente. */
export class RessourceIntrouvableError extends Error {
  constructor(cle: string) {
    super(`Ressource introuvable : ${cle}`);
    this.name = 'RessourceIntrouvableError';
  }
}

/** Levée quand la source elle-même est indisponible -> HTTP 502. */
export class SourceIndisponibleError extends Error {
  constructor(libelle: string, cause?: unknown) {
    super(`Source indisponible : ${libelle}${cause ? ` (${String(cause)})` : ''}`);
    this.name = 'SourceIndisponibleError';
  }
}
