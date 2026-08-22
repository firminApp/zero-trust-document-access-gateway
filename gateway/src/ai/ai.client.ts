import { Injectable, Logger } from '@nestjs/common';
import { ActionAcces, EntiteAnalysee, NiveauSens } from '../common/types';

/**
 * Client HTTP du moteur IA.
 *
 * Le moteur n'est joignable que sur le réseau Docker interne. C'est le seul
 * composant à qui la passerelle transmet des octets de documents, et le seul
 * d'où reviennent des valeurs d'entités en clair — que `CatalogService` hache
 * immédiatement avant toute persistance.
 */

export interface ReponseAnalyse {
  texteExtrait: boolean;
  methodeExtraction: 'pdf' | 'docx' | 'plain' | 'ocr' | 'aucune';
  cerEstime: number | null;
  entites: EntiteAnalysee[];
  niveauMax: NiveauSens | null;
  nbCaracteres: number;
  nbPages: number | null;
}

export interface Correspondance {
  empreinte: string;
  jeton: string;
  valeurChiffreeBase64: string | null;
}

export interface ReponseProtection {
  contenu: Buffer;
  nbEntitesProtegees: number;
  typeMimeSortie: string;
  correspondances: Correspondance[];
}

export class MoteurIaIndisponibleError extends Error {
  constructor(cause: unknown) {
    super(`Moteur IA injoignable : ${String(cause)}`);
    this.name = 'MoteurIaIndisponibleError';
  }
}

@Injectable()
export class AiClient {
  private readonly logger = new Logger(AiClient.name);
  private readonly base = process.env.AI_ENGINE_URL ?? 'http://moteur-ia:8000';
  private readonly delaiMs = Number(process.env.AI_TIMEOUT_MS ?? 120_000);

  async analyser(entree: {
    documentId: string;
    typeMime: string | null;
    contenu: Buffer;
    nomFichier?: string;
  }): Promise<ReponseAnalyse> {
    return this.appeler<ReponseAnalyse>('/analyser', {
      documentId: entree.documentId,
      typeMime: entree.typeMime,
      contenuBase64: entree.contenu.toString('base64'),
      nomFichier: entree.nomFichier ?? null,
    });
  }

  async proteger(entree: {
    documentId: string;
    typeMime: string | null;
    contenu: Buffer;
    action: Extract<ActionAcces, 'masque' | 'pseudonymise'>;
    niveauSeuil: NiveauSens;
    nomFichier?: string;
  }): Promise<ReponseProtection> {
    const reponse = await this.appeler<{
      contenuBase64: string;
      nbEntitesProtegees: number;
      typeMimeSortie: string;
      correspondances?: Correspondance[];
    }>('/proteger', {
      documentId: entree.documentId,
      typeMime: entree.typeMime,
      contenuBase64: entree.contenu.toString('base64'),
      action: entree.action,
      niveauSeuil: entree.niveauSeuil,
      nomFichier: entree.nomFichier ?? null,
    });

    return {
      contenu: Buffer.from(reponse.contenuBase64, 'base64'),
      nbEntitesProtegees: reponse.nbEntitesProtegees,
      typeMimeSortie: reponse.typeMimeSortie,
      correspondances: reponse.correspondances ?? [],
    };
  }

  async sante(): Promise<{ statut: string; modeleNer: string; versionTesseract: string }> {
    return this.appeler('/sante', undefined, 'GET');
  }

  private async appeler<T>(
    chemin: string,
    corps?: unknown,
    methode: 'GET' | 'POST' = 'POST',
  ): Promise<T> {
    const controleur = new AbortController();
    const minuterie = setTimeout(() => controleur.abort(), this.delaiMs);

    try {
      const reponse = await fetch(`${this.base}${chemin}`, {
        method: methode,
        headers: corps ? { 'Content-Type': 'application/json' } : undefined,
        body: corps ? JSON.stringify(corps) : undefined,
        signal: controleur.signal,
      });

      if (!reponse.ok) {
        const detail = await reponse.text().catch(() => '');
        throw new Error(`HTTP ${reponse.status} sur ${chemin} : ${detail.slice(0, 300)}`);
      }

      return (await reponse.json()) as T;
    } catch (erreur) {
      this.logger.error(`Appel ${methode} ${chemin} en échec : ${String(erreur)}`);
      throw new MoteurIaIndisponibleError(erreur);
    } finally {
      clearTimeout(minuterie);
    }
  }
}
