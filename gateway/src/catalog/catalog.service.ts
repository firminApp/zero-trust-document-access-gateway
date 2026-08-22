import { Inject, Injectable } from '@nestjs/common';
import { createHash } from 'node:crypto';
import { Pool } from 'pg';
import {
  DocumentCatalogue,
  EntiteAnalysee,
  NiveauSens,
  Source,
  StatutDoc,
  TypeSource,
} from '../common/types';
import { PG_POOL } from '../db/database.module';

interface LigneDocument {
  id: string;
  source_id: string;
  chemin_source: string;
  empreinte_sha256: string;
  type_mime: string | null;
  taille_octets: string | null;
  statut: StatutDoc;
  niveau_max: NiveauSens | null;
  date_decouverte: Date;
  date_analyse: Date | null;
  tentatives: number;
  motif_echec: string | null;
}

interface LigneSource {
  id: string;
  type: TypeSource;
  libelle: string;
  configuration: Record<string, unknown>;
  frequence_cron: string;
  dernier_scan: Date | null;
  actif: boolean;
}

/**
 * Accès au catalogue (documents, entités, sources).
 *
 * Invariant appliqué ici et nulle part ailleurs : **aucune valeur d'entité
 * personnelle n'est écrite en base**. `enregistrerEntites()` reçoit les valeurs
 * en clair depuis le moteur IA et n'en persiste que l'empreinte salée, le type
 * et la position. Sans cette barrière, le catalogue deviendrait la base de
 * données personnelles la plus dense de l'entreprise (ADR n°6).
 */
@Injectable()
export class CatalogService {

  constructor(@Inject(PG_POOL) private readonly pool: Pool) {}

  /** SHA-256(valeur || sel serveur). Le sel empêche l'attaque par dictionnaire. */
  static empreinteValeur(valeur: string, sel = process.env.HASH_SALT ?? 'change-me'): string {
    const canonique = valeur
      .normalize('NFKD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .trim()
      .replace(/\s+/g, ' ');
    return createHash('sha256').update(`${canonique}${sel}`, 'utf8').digest('hex');
  }

  static empreinteContenu(contenu: Buffer): string {
    return createHash('sha256').update(contenu).digest('hex');
  }

  // --- Sources ---------------------------------------------------------------

  async sources(actifsSeulement = false): Promise<Source[]> {
    const { rows } = await this.pool.query<LigneSource>(
      `SELECT * FROM source ${actifsSeulement ? 'WHERE actif = true' : ''} ORDER BY libelle`,
    );
    return rows.map(CatalogService.versSource);
  }

  async source(id: string): Promise<Source | null> {
    const { rows } = await this.pool.query<LigneSource>('SELECT * FROM source WHERE id = $1', [
      id,
    ]);
    return rows[0] ? CatalogService.versSource(rows[0]) : null;
  }

  async creerSource(entree: {
    type: TypeSource;
    libelle: string;
    configuration: Record<string, unknown>;
    frequenceCron?: string;
  }): Promise<Source> {
    const { rows } = await this.pool.query<LigneSource>(
      `INSERT INTO source (type, libelle, configuration, frequence_cron)
       VALUES ($1, $2, $3::jsonb, $4) RETURNING *`,
      [
        entree.type,
        entree.libelle,
        JSON.stringify(entree.configuration),
        entree.frequenceCron ?? '0 2 * * *',
      ],
    );
    return CatalogService.versSource(rows[0]);
  }

  async marquerScan(sourceId: string): Promise<void> {
    await this.pool.query('UPDATE source SET dernier_scan = now() WHERE id = $1', [sourceId]);
  }

  // --- Documents -------------------------------------------------------------

  async document(id: string): Promise<DocumentCatalogue | null> {
    const { rows } = await this.pool.query<LigneDocument>(
      'SELECT * FROM document WHERE id = $1',
      [id],
    );
    return rows[0] ? CatalogService.versDocument(rows[0]) : null;
  }

  async lister(filtres: {
    sourceId?: string;
    statut?: StatutDoc;
    niveau?: NiveauSens;
    page?: number;
    taille?: number;
  }): Promise<{ total: number; documents: DocumentCatalogue[] }> {
    const conditions: string[] = [];
    const valeurs: unknown[] = [];

    if (filtres.sourceId) {
      valeurs.push(filtres.sourceId);
      conditions.push(`source_id = $${valeurs.length}`);
    }
    if (filtres.statut) {
      valeurs.push(filtres.statut);
      conditions.push(`statut = $${valeurs.length}`);
    }
    if (filtres.niveau) {
      valeurs.push(filtres.niveau);
      conditions.push(`niveau_max = $${valeurs.length}`);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
    const taille = Math.min(Math.max(filtres.taille ?? 50, 1), 500);
    const page = Math.max(filtres.page ?? 1, 1);

    const { rows: compte } = await this.pool.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM document ${where}`,
      valeurs,
    );

    valeurs.push(taille, (page - 1) * taille);
    const { rows } = await this.pool.query<LigneDocument>(
      `SELECT * FROM document ${where}
        ORDER BY date_decouverte DESC
        LIMIT $${valeurs.length - 1} OFFSET $${valeurs.length}`,
      valeurs,
    );

    return {
      total: Number(compte[0]?.total ?? 0),
      documents: rows.map(CatalogService.versDocument),
    };
  }

  /**
   * Enregistre une ressource découverte.
   *
   * @returns `null` si le document existe déjà avec la même empreinte — c'est
   *          ce court-circuit qui rend le coût d'un scan proportionnel aux
   *          nouveautés et non au volume total (M2).
   */
  async upsertDocument(entree: {
    sourceId: string;
    cheminSource: string;
    empreinteSha256: string;
    typeMime?: string | null;
    tailleOctets?: number | null;
  }): Promise<DocumentCatalogue | null> {
    const { rows } = await this.pool.query<LigneDocument>(
      `INSERT INTO document (source_id, chemin_source, empreinte_sha256, type_mime, taille_octets)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (source_id, chemin_source) DO UPDATE
         SET empreinte_sha256 = EXCLUDED.empreinte_sha256,
             type_mime        = EXCLUDED.type_mime,
             taille_octets    = EXCLUDED.taille_octets,
             statut           = 'decouvert',
             niveau_max       = NULL,
             date_analyse     = NULL,
             tentatives       = 0,
             motif_echec      = NULL
       WHERE document.empreinte_sha256 <> EXCLUDED.empreinte_sha256
       RETURNING *`,
      [
        entree.sourceId,
        entree.cheminSource,
        entree.empreinteSha256,
        entree.typeMime ?? null,
        entree.tailleOctets ?? null,
      ],
    );

    return rows[0] ? CatalogService.versDocument(rows[0]) : null;
  }

  async marquerStatut(
    documentId: string,
    statut: StatutDoc,
    motifEchec?: string,
  ): Promise<void> {
    // `$2` est transtypé explicitement : sans cela PostgreSQL doit déduire son
    // type à la fois d'une affectation à une colonne `statut_doc` et d'une
    // comparaison textuelle, et rejette la requête.
    await this.pool.query(
      `UPDATE document
          SET statut = $2::statut_doc,
              motif_echec = $3,
              tentatives = CASE WHEN $2::statut_doc = 'echec'
                                THEN tentatives + 1 ELSE tentatives END
        WHERE id = $1`,
      [documentId, statut, motifEchec ?? null],
    );
  }

  /**
   * Persiste le résultat d'une analyse.
   *
   * Les valeurs reçues du moteur IA sont hachées ici et jamais journalisées.
   * L'opération est transactionnelle : un document ne doit jamais passer à
   * `analyse` si ses entités n'ont pas été écrites.
   */
  async enregistrerEntites(
    documentId: string,
    entites: EntiteAnalysee[],
    niveauMax: NiveauSens | null,
  ): Promise<void> {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      await client.query('DELETE FROM entite_detectee WHERE document_id = $1', [documentId]);

      for (const entite of entites) {
        await client.query(
          `INSERT INTO entite_detectee
             (document_id, type_entite, empreinte_valeur, position_debut, position_fin,
              page, niveau_sensibilite, score_confiance, methode)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
          [
            documentId,
            entite.typeEntite,
            CatalogService.empreinteValeur(entite.valeur),
            entite.debut,
            entite.fin,
            entite.page,
            entite.niveau,
            entite.score,
            entite.methode,
          ],
        );
      }

      await client.query(
        `UPDATE document
            SET statut = 'analyse', niveau_max = $2, date_analyse = now(), motif_echec = NULL
          WHERE id = $1`,
        [documentId, niveauMax],
      );

      await client.query('COMMIT');
    } catch (erreur) {
      await client.query('ROLLBACK').catch(() => undefined);
      throw erreur;
    } finally {
      client.release();
    }
  }

  /** Métadonnées d'entités exposées par l'API : type, niveau, page. Jamais de valeur. */
  async entitesDe(
    documentId: string,
  ): Promise<Array<{ typeEntite: string; niveau: NiveauSens; page: number | null }>> {
    const { rows } = await this.pool.query<{
      type_entite: string;
      niveau_sensibilite: NiveauSens;
      page: number | null;
    }>(
      `SELECT type_entite, niveau_sensibilite, page
         FROM entite_detectee WHERE document_id = $1
        ORDER BY position_debut`,
      [documentId],
    );
    return rows.map((r) => ({
      typeEntite: r.type_entite,
      niveau: r.niveau_sensibilite,
      page: r.page,
    }));
  }

  // --- Pseudonymes -----------------------------------------------------------

  /** Enregistre une correspondance de pseudonymisation (valeur déjà chiffrée). */
  async enregistrerPseudonyme(lien: {
    empreinte: string;
    jeton: string;
    valeurChiffreeBase64: string;
  }): Promise<void> {
    await this.pool.query(
      `INSERT INTO pseudonyme (empreinte_valeur, jeton, valeur_chiffree)
       VALUES ($1, $2, decode($3, 'base64'))
       ON CONFLICT (empreinte_valeur) DO NOTHING`,
      [lien.empreinte, lien.jeton, lien.valeurChiffreeBase64],
    );
  }

  // --- Conversions -----------------------------------------------------------

  private static versSource(ligne: LigneSource): Source {
    return {
      id: ligne.id,
      type: ligne.type,
      libelle: ligne.libelle,
      configuration: ligne.configuration,
      frequenceCron: ligne.frequence_cron,
      dernierScan: ligne.dernier_scan,
      actif: ligne.actif,
    };
  }

  private static versDocument(ligne: LigneDocument): DocumentCatalogue {
    return {
      id: ligne.id,
      sourceId: ligne.source_id,
      cheminSource: ligne.chemin_source,
      empreinteSha256: ligne.empreinte_sha256,
      typeMime: ligne.type_mime,
      tailleOctets: ligne.taille_octets === null ? null : Number(ligne.taille_octets),
      statut: ligne.statut,
      niveauMax: ligne.niveau_max,
      dateDecouverte: ligne.date_decouverte,
      dateAnalyse: ligne.date_analyse,
      tentatives: ligne.tentatives,
      motifEchec: ligne.motif_echec,
    };
  }
}
