import { Injectable, Logger, OnApplicationShutdown, OnModuleInit } from '@nestjs/common';
import { Job, Worker } from 'bullmq';
import { AiClient } from '../ai/ai.client';
import { CatalogService } from '../catalog/catalog.service';
import { ConnectorFactory } from '../connectors/connector.factory';
import { creerConnexionRedis, NOM_FILE, TacheAnalyse, TacheScan } from './queue';
import { ScanService } from './scan.service';

/**
 * Worker BullMQ de l'orchestrateur.
 *
 * Il ne tourne que dans le conteneur `orchestrateur` : la passerelle sert des
 * requêtes, l'orchestrateur fait le travail long. Séparer les deux évite
 * qu'une campagne d'analyse dégrade la latence de restitution (cible p95 ≤ 2 s).
 */
@Injectable()
export class ScanProcessor implements OnModuleInit, OnApplicationShutdown {
  private readonly logger = new Logger(ScanProcessor.name);
  private worker: Worker | null = null;
  private readonly connexion = creerConnexionRedis();

  constructor(
    private readonly catalogue: CatalogService,
    private readonly connecteurs: ConnectorFactory,
    private readonly ia: AiClient,
    private readonly scans: ScanService,
  ) {}

  onModuleInit(): void {
    this.worker = new Worker(
      NOM_FILE,
      async (tache: Job) => {
        if (tache.name === 'scan') {
          return this.traiterScan(tache.data as TacheScan);
        }
        if (tache.name === 'analyse') {
          return this.traiterAnalyse(tache.data as TacheAnalyse);
        }
        this.logger.warn(`Tâche inconnue ignorée : ${tache.name}`);
        return undefined;
      },
      {
        connection: this.connexion,
        concurrency: Number(process.env.WORKER_CONCURRENCE ?? 4),
      },
    );

    this.worker.on('failed', (tache, erreur) => {
      this.logger.error(`Tâche ${tache?.name}#${tache?.id} en échec : ${erreur.message}`);
    });

    this.logger.log('Worker démarré');
  }

  private async traiterScan(tache: TacheScan): Promise<void> {
    const source = await this.catalogue.source(tache.sourceId);
    if (!source) {
      this.logger.warn(`Source ${tache.sourceId} introuvable, scan abandonné`);
      return;
    }
    // Reprise d'abord : le scan lui-même ignore les ressources
    // inchangées, il ne rattraperait donc jamais un document resté en
    // « decouvert » ou en « echec ».
    await this.scans.replanifierEnAttente(source.id);
    await this.scans.scanner(source, tache.declencheur);
  }

  /**
   * Analyse d'un document : lecture des octets, appel du moteur, persistance.
   *
   * Les valeurs d'entités reçues du moteur ne sont **ni journalisées ni
   * loguées** : `enregistrerEntites` les hache, et rien d'autre ici ne les
   * touche.
   */
  private async traiterAnalyse(tache: TacheAnalyse): Promise<void> {
    const document = await this.catalogue.document(tache.documentId);
    if (!document) {
      this.logger.warn(`Document ${tache.documentId} absent du catalogue`);
      return;
    }

    const source = await this.catalogue.source(document.sourceId);
    if (!source) {
      await this.catalogue.marquerStatut(document.id, 'echec', 'source_introuvable');
      return;
    }

    await this.catalogue.marquerStatut(document.id, 'en_analyse');

    try {
      const contenu = await this.connecteurs.pour(source).lire(document.cheminSource);
      const analyse = await this.ia.analyser({
        documentId: document.id,
        typeMime: document.typeMime,
        contenu,
        nomFichier: document.cheminSource,
      });

      await this.catalogue.enregistrerEntites(
        document.id,
        analyse.entites,
        analyse.niveauMax,
      );

      this.logger.log(
        `Analysé ${document.cheminSource} : ${analyse.entites.length} entité(s), ` +
          `niveau=${analyse.niveauMax ?? 'aucun'} (${analyse.methodeExtraction})`,
      );
    } catch (erreur) {
      const motif = (erreur as Error).message.slice(0, 500);
      await this.catalogue.marquerStatut(document.id, 'echec', motif);
      this.logger.error(`Analyse en échec pour ${document.cheminSource} : ${motif}`);
      throw erreur; // laisse BullMQ appliquer sa politique de reprise
    }
  }

  async onApplicationShutdown(): Promise<void> {
    await this.worker?.close().catch(() => undefined);
    this.connexion.disconnect();
  }
}
