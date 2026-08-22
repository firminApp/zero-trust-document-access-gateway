import { Inject, Injectable, Logger } from '@nestjs/common';
import { createHash } from 'node:crypto';
import { Pool, PoolClient } from 'pg';
import { PG_POOL } from '../db/database.module';
import { ActionAcces, ActionAudit, NiveauSens } from '../common/types';

/**
 * Journal d'audit append-only, chaîné cryptographiquement.
 *
 *   empreinte(n) = SHA256(empreinte(n-1) || utilisateur_id || role_effectif ||
 *                         document_id || action || politique_appliquee ||
 *                         horodatage_iso8601)
 *
 * Deux propriétés en découlent :
 *   * toute modification d'une entrée casse le chaînage à partir d'elle ;
 *   * toute suppression casse le chaînage au point de la coupure.
 *
 * Un journal modifiable par celui qu'il surveille ne prouve rien : c'est la
 * raison d'être du chaînage et des règles SQL `DO INSTEAD NOTHING`.
 */

export interface EntreeAudit {
  utilisateurId: string;
  roleEffectif: string;
  documentId?: string | null;
  action: ActionAudit | string;
  politiqueAppliquee?: ActionAcces | null;
  niveauEnCause?: NiveauSens | null;
  adresseIp?: string | null;
  details?: Record<string, unknown> | null;
}

export interface LigneAudit {
  id: string;
  horodatage: Date;
  utilisateurId: string;
  roleEffectif: string;
  documentId: string | null;
  action: string;
  politiqueAppliquee: ActionAcces | null;
  niveauEnCause: NiveauSens | null;
  adresseIp: string | null;
  details: Record<string, unknown> | null;
  empreintePrecedente: string | null;
  empreinte: string;
}

export interface ResultatVerification {
  intact: boolean;
  premiereRupture: string | null;
  nbEntrees: number;
}

/** Empreinte de la chaîne vide : ancre de la chaîne (`empreinte(0)`). */
export const EMPREINTE_GENESE = createHash('sha256').update('').digest('hex');

@Injectable()
export class AuditService {
  private readonly logger = new Logger(AuditService.name);

  constructor(@Inject(PG_POOL) private readonly pool: Pool) {}

  /**
   * Calcule l'empreinte d'une entrée. Fonction pure : c'est elle qui est
   * rejouée par `verifyChain()`, donc elle ne doit dépendre d'aucun état.
   */
  static calculerEmpreinte(params: {
    empreintePrecedente: string | null;
    utilisateurId: string;
    roleEffectif: string;
    documentId: string | null;
    action: string;
    politiqueAppliquee: string | null;
    horodatageIso: string;
  }): string {
    const contenu = [
      params.empreintePrecedente ?? EMPREINTE_GENESE,
      params.utilisateurId,
      params.roleEffectif,
      params.documentId ?? '',
      params.action,
      params.politiqueAppliquee ?? '',
      params.horodatageIso,
    ].join('|');
    return createHash('sha256').update(contenu, 'utf8').digest('hex');
  }

  /**
   * Ajoute une entrée au journal.
   *
   * La lecture de la dernière empreinte et l'insertion se font dans une même
   * transaction SERIALIZABLE : sans cela, deux requêtes concurrentes liraient
   * la même empreinte précédente et produiraient deux maillons frères, ce qui
   * casse la chaîne (piège n°7).
   */
  async append(entree: EntreeAudit): Promise<string> {
    const MAX_TENTATIVES = 5;

    for (let tentative = 1; tentative <= MAX_TENTATIVES; tentative += 1) {
      const client = await this.pool.connect();
      try {
        return await this.inserer(client, entree);
      } catch (erreur) {
        const code = (erreur as { code?: string }).code;
        // 40001 : échec de sérialisation. La transaction perdante rejoue.
        if (code === '40001' && tentative < MAX_TENTATIVES) {
          await this.attendre(10 * tentative);
          continue;
        }
        throw erreur;
      } finally {
        client.release();
      }
    }

    throw new Error("Impossible d'écrire au journal d'audit après plusieurs tentatives");
  }

  private async inserer(client: PoolClient, entree: EntreeAudit): Promise<string> {
    try {
      await client.query('BEGIN ISOLATION LEVEL SERIALIZABLE');

      const { rows: dernieres } = await client.query<{ empreinte: string }>(
        'SELECT empreinte FROM journal_audit ORDER BY id DESC LIMIT 1',
      );
      const empreintePrecedente = dernieres[0]?.empreinte ?? null;

      const horodatage = new Date();
      const empreinte = AuditService.calculerEmpreinte({
        empreintePrecedente,
        utilisateurId: entree.utilisateurId,
        roleEffectif: entree.roleEffectif,
        documentId: entree.documentId ?? null,
        action: entree.action,
        politiqueAppliquee: entree.politiqueAppliquee ?? null,
        horodatageIso: horodatage.toISOString(),
      });

      const { rows } = await client.query<{ id: string }>(
        `INSERT INTO journal_audit
           (horodatage, utilisateur_id, role_effectif, document_id, action,
            politique_appliquee, niveau_en_cause, adresse_ip, details,
            empreinte_precedente, empreinte)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
         RETURNING id`,
        [
          horodatage,
          entree.utilisateurId,
          entree.roleEffectif,
          entree.documentId ?? null,
          entree.action,
          entree.politiqueAppliquee ?? null,
          entree.niveauEnCause ?? null,
          entree.adresseIp ?? null,
          entree.details ? JSON.stringify(entree.details) : null,
          empreintePrecedente,
          empreinte,
        ],
      );

      await client.query('COMMIT');
      return rows[0].id;
    } catch (erreur) {
      await client.query('ROLLBACK').catch(() => undefined);
      throw erreur;
    }
  }

  /**
   * Rejoue le chaînage du début à la fin.
   *
   * @returns l'id de la première entrée incohérente, ou `null` si la chaîne
   *          est intacte.
   */
  async verifyChain(): Promise<ResultatVerification> {
    const TAILLE_LOT = 1000;
    let dernierId = '0';
    let empreintePrecedente: string | null = null;
    let nbEntrees = 0;

    for (;;) {
      const { rows } = await this.pool.query<{
        id: string;
        horodatage: Date;
        utilisateur_id: string;
        role_effectif: string;
        document_id: string | null;
        action: string;
        politique_appliquee: string | null;
        empreinte_precedente: string | null;
        empreinte: string;
      }>(
        `SELECT id, horodatage, utilisateur_id, role_effectif, document_id,
                action, politique_appliquee, empreinte_precedente, empreinte
           FROM journal_audit
          WHERE id > $1
          ORDER BY id ASC
          LIMIT $2`,
        [dernierId, TAILLE_LOT],
      );

      if (rows.length === 0) {
        break;
      }

      for (const ligne of rows) {
        nbEntrees += 1;

        // Le maillon doit pointer vers l'empreinte de son prédécesseur.
        if ((ligne.empreinte_precedente ?? null) !== empreintePrecedente) {
          return { intact: false, premiereRupture: ligne.id, nbEntrees };
        }

        const attendue = AuditService.calculerEmpreinte({
          empreintePrecedente,
          utilisateurId: ligne.utilisateur_id,
          roleEffectif: ligne.role_effectif,
          documentId: ligne.document_id,
          action: ligne.action,
          politiqueAppliquee: ligne.politique_appliquee,
          horodatageIso: new Date(ligne.horodatage).toISOString(),
        });

        if (attendue !== ligne.empreinte) {
          this.logger.error(`Chaîne d'audit rompue à l'entrée ${ligne.id}`);
          return { intact: false, premiereRupture: ligne.id, nbEntrees };
        }

        empreintePrecedente = ligne.empreinte;
        dernierId = ligne.id;
      }
    }

    return { intact: true, premiereRupture: null, nbEntrees };
  }

  async rechercher(filtres: {
    documentId?: string;
    utilisateurId?: string;
    depuis?: string;
    jusqua?: string;
    page?: number;
    taille?: number;
  }): Promise<{ total: number; entrees: LigneAudit[] }> {
    const conditions: string[] = [];
    const valeurs: unknown[] = [];

    if (filtres.documentId) {
      valeurs.push(filtres.documentId);
      conditions.push(`document_id = $${valeurs.length}`);
    }
    if (filtres.utilisateurId) {
      valeurs.push(filtres.utilisateurId);
      conditions.push(`utilisateur_id = $${valeurs.length}`);
    }
    if (filtres.depuis) {
      valeurs.push(filtres.depuis);
      conditions.push(`horodatage >= $${valeurs.length}`);
    }
    if (filtres.jusqua) {
      valeurs.push(filtres.jusqua);
      conditions.push(`horodatage <= $${valeurs.length}`);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
    const taille = Math.min(Math.max(filtres.taille ?? 50, 1), 500);
    const page = Math.max(filtres.page ?? 1, 1);

    const { rows: compte } = await this.pool.query<{ total: string }>(
      `SELECT count(*)::text AS total FROM journal_audit ${where}`,
      valeurs,
    );

    valeurs.push(taille, (page - 1) * taille);
    const { rows } = await this.pool.query(
      `SELECT * FROM journal_audit ${where}
        ORDER BY id DESC
        LIMIT $${valeurs.length - 1} OFFSET $${valeurs.length}`,
      valeurs,
    );

    return {
      total: Number(compte[0]?.total ?? 0),
      entrees: rows.map((ligne) => ({
        id: String(ligne.id),
        horodatage: ligne.horodatage,
        utilisateurId: ligne.utilisateur_id,
        roleEffectif: ligne.role_effectif,
        documentId: ligne.document_id,
        action: ligne.action,
        politiqueAppliquee: ligne.politique_appliquee,
        niveauEnCause: ligne.niveau_en_cause,
        adresseIp: ligne.adresse_ip,
        details: ligne.details,
        empreintePrecedente: ligne.empreinte_precedente,
        empreinte: ligne.empreinte,
      })),
    };
  }

  private attendre(ms: number): Promise<void> {
    return new Promise((resoudre) => setTimeout(resoudre, ms));
  }
}
