import { Inject, Injectable, Logger } from '@nestjs/common';
import { Pool } from 'pg';
import { AuditService } from '../audit/audit.service';
import { CatalogService } from '../catalog/catalog.service';
import { ACTIONS_AUDIT, Source } from '../common/types';
import { ConnectorFactory } from '../connectors/connector.factory';
import { PG_POOL } from '../db/database.module';
import { FileTaches } from './queue';

export const TAILLE_LOT = 200;

export interface ResultatScan {
  sourceId: string;
  nbListes: number;
  nbNouveaux: number;
  nbInchanges: number;
  nbEchecs: number;
}

/**
 * Scan incrémental d'une source (M2).
 *
 * Le point qui fait tout l'intérêt du traitement incrémental est à l'étape 2 :
 * si `(source_id, chemin)` existe déjà avec la même empreinte, on ignore. Le
 * coût d'un scan devient proportionnel aux nouveautés, pas au patrimoine.
 *
 * Un échec unitaire n'interrompt jamais le lot : un fichier corrompu ne doit
 * pas empêcher les 199 autres d'être catalogués.
 */
@Injectable()
export class ScanService {
  private readonly logger = new Logger(ScanService.name);

  constructor(
    @Inject(PG_POOL) private readonly pool: Pool,
    private readonly catalogue: CatalogService,
    private readonly connecteurs: ConnectorFactory,
    private readonly file: FileTaches,
    private readonly audit: AuditService,
  ) {}

  async scanner(source: Source, declencheur: 'cron' | 'manuel'): Promise<ResultatScan> {
    const executionId = await this.ouvrirExecution(source.id, declencheur);
    const connecteur = this.connecteurs.pour(source);

    const resultat: ResultatScan = {
      sourceId: source.id,
      nbListes: 0,
      nbNouveaux: 0,
      nbInchanges: 0,
      nbEchecs: 0,
    };

    let lot: string[] = [];

    try {
      for await (const ressource of connecteur.lister()) {
        resultat.nbListes += 1;

        try {
          const contenu = await connecteur.lire(ressource.cle);
          const empreinte = CatalogService.empreinteContenu(contenu);

          const document = await this.catalogue.upsertDocument({
            sourceId: source.id,
            cheminSource: ressource.cle,
            empreinteSha256: empreinte,
            typeMime: ressource.typeMime ?? null,
            tailleOctets: ressource.taille,
          });

          if (!document) {
            // Empreinte identique : rien n'a changé, on n'analyse pas.
            resultat.nbInchanges += 1;
            continue;
          }

          resultat.nbNouveaux += 1;
          lot.push(document.id);

          if (lot.length >= TAILLE_LOT) {
            await this.file.planifierAnalyses(lot);
            lot = [];
          }
        } catch (erreur) {
          resultat.nbEchecs += 1;
          this.logger.warn(
            `Ressource « ${ressource.cle} » ignorée : ${(erreur as Error).message}`,
          );
        }
      }

      await this.file.planifierAnalyses(lot);
      await this.catalogue.marquerScan(source.id);
    } finally {
      await this.fermerExecution(executionId, resultat);
    }

    await this.audit.append({
      utilisateurId: declencheur === 'cron' ? 'systeme' : 'orchestrateur',
      roleEffectif: 'systeme',
      action: ACTIONS_AUDIT.SCAN,
      adresseIp: null,
      details: { source: source.libelle, declencheur, ...resultat },
    });

    this.logger.log(
      `Scan « ${source.libelle} » : ${resultat.nbListes} listés, ` +
        `${resultat.nbNouveaux} nouveaux, ${resultat.nbInchanges} inchangés, ` +
        `${resultat.nbEchecs} échecs`,
    );
    return resultat;
  }

  private async ouvrirExecution(sourceId: string, declencheur: string): Promise<string> {
    const { rows } = await this.pool.query<{ id: string }>(
      'INSERT INTO scan_execution (source_id, declencheur) VALUES ($1, $2) RETURNING id',
      [sourceId, declencheur],
    );
    return rows[0].id;
  }

  private async fermerExecution(id: string, resultat: ResultatScan): Promise<void> {
    await this.pool.query(
      `UPDATE scan_execution
          SET termine_le = now(), nb_listes = $2, nb_nouveaux = $3,
              nb_inchanges = $4, nb_echecs = $5
        WHERE id = $1`,
      [id, resultat.nbListes, resultat.nbNouveaux, resultat.nbInchanges, resultat.nbEchecs],
    );
  }

  /**
   * Remet en file tout document qui n'est pas encore analysé.
   *
   * Appelé au début de chaque scan. Trois situations le rendent nécessaire, et
   * aucune n'est rattrapée par le scan lui-même — celui-ci ignore par
   * construction les ressources dont l'empreinte n'a pas changé :
   *
   *   * `echec`      — panne transitoire (moteur IA redémarré, fichier
   *                    verrouillé) ; on réessaie tant que `tentatives < 3` ;
   *   * `decouvert`  — le worker s'est arrêté entre l'inscription au catalogue
   *                    et la mise en file ; sans cette reprise le document
   *                    resterait indéfiniment non analysé, donc indéfiniment
   *                    en 423 ;
   *   * `en_analyse` — tâche interrompue en cours de traitement.
   *
   * C'est ce qui rend le système convergent : tout document finit analysé, ou
   * marqué en échec après trois tentatives.
   */
  async replanifierEnAttente(sourceId: string, maxTentatives = 3): Promise<number> {
    const { rows } = await this.pool.query<{ id: string }>(
      `SELECT id FROM document
        WHERE source_id = $1
          AND statut <> 'analyse'
          AND (statut <> 'echec' OR tentatives < $2)
        ORDER BY date_decouverte
        LIMIT $3`,
      [sourceId, maxTentatives, TAILLE_LOT],
    );
    await this.file.planifierAnalyses(rows.map((r) => r.id));
    if (rows.length > 0) {
      this.logger.log(`${rows.length} document(s) remis en file pour analyse`);
    }
    return rows.length;
  }
}
