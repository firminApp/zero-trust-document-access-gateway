import { Global, Injectable, Logger, Module, OnApplicationShutdown } from '@nestjs/common';
import { Queue } from 'bullmq';
import IORedis, { Redis } from 'ioredis';

export const NOM_FILE = 'ztg';

export type NomTache = 'scan' | 'analyse';

export interface TacheScan {
  sourceId: string;
  declencheur: 'cron' | 'manuel';
}

export interface TacheAnalyse {
  documentId: string;
}

export function creerConnexionRedis(): Redis {
  return new IORedis(process.env.REDIS_URL ?? 'redis://localhost:6379', {
    // Exigé par BullMQ : sans cela un worker abandonne la tâche au premier
    // hoquet réseau au lieu de la reprendre.
    maxRetriesPerRequest: null,
    enableReadyCheck: false,
  });
}

/** Producteur de tâches, partagé par le déclencheur manuel et le cron. */
@Injectable()
export class FileTaches implements OnApplicationShutdown {
  private readonly logger = new Logger(FileTaches.name);
  private readonly connexion = creerConnexionRedis();
  readonly queue = new Queue(NOM_FILE, { connection: this.connexion });

  async planifierScan(tache: TacheScan): Promise<void> {
    await this.queue.add('scan', tache, {
      // Un scan par source à la fois : deux exécutions simultanées sur la même
      // source produiraient des doublons (critère d'idempotence M2).
      // BullMQ interdit « : » dans un identifiant de tâche personnalisé.
      jobId: `scan-${tache.sourceId}`,
      // Retrait immédiat en fin de traitement. Avec une rétention, l'ancienne
      // tâche garde son identifiant et BullMQ ignore SILENCIEUSEMENT tout
      // nouvel `add` portant le même : le scan suivant ne partirait jamais.
      // L'identifiant ne doit exister que le temps où la tâche est en file ou
      // en cours — c'est exactement la sémantique « un scan à la fois ».
      // L'historique durable est en base (`scan_execution`), pas dans Redis.
      removeOnComplete: true,
      removeOnFail: true,
    });
    this.logger.log(`Scan planifié pour la source ${tache.sourceId} (${tache.declencheur})`);
  }

  async planifierAnalyses(documentIds: string[]): Promise<void> {
    if (documentIds.length === 0) {
      return;
    }
    await this.queue.addBulk(
      documentIds.map((documentId) => ({
        name: 'analyse' as const,
        data: { documentId },
        opts: {
          jobId: `analyse-${documentId}`,
          attempts: 3,
          backoff: { type: 'exponential' as const, delay: 5_000 },
          // Même raison que pour les scans, et elle est ici plus visible
          // encore : l'identifiant d'un document est stable dans le temps.
          // Retenir la tâche terminée empêcherait toute réanalyse après
          // modification du fichier — le document resterait figé sur son
          // ancienne classification. L'état durable est `document.statut`.
          removeOnComplete: true,
          removeOnFail: true,
        },
      })),
    );
  }

  async onApplicationShutdown(): Promise<void> {
    await this.queue.close().catch(() => undefined);
    this.connexion.disconnect();
  }
}

@Global()
@Module({
  providers: [FileTaches],
  exports: [FileTaches],
})
export class QueueModule {}
