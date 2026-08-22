import { Injectable, Logger, OnApplicationShutdown, OnModuleInit } from '@nestjs/common';
import * as cron from 'node-cron';
import { CatalogService } from '../catalog/catalog.service';
import { FileTaches } from './queue';

/**
 * Planification des scans par `frequence_cron`, une tâche par source active.
 *
 * Le cron ne fait qu'**émettre une tâche** : le travail réel se déroule dans
 * le worker. Si un scan dure plus longtemps que sa période, le `jobId`
 * déterministe (`scan:<sourceId>`) empêche la seconde exécution de démarrer
 * en parallèle.
 */
@Injectable()
export class SchedulerService implements OnModuleInit, OnApplicationShutdown {
  private readonly logger = new Logger(SchedulerService.name);
  private readonly taches = new Map<string, cron.ScheduledTask>();

  constructor(
    private readonly catalogue: CatalogService,
    private readonly file: FileTaches,
  ) {}

  async onModuleInit(): Promise<void> {
    await this.recharger();
    // Les sources déclarées après le démarrage sont prises en compte au
    // rechargement périodique, sans redémarrer l'orchestrateur.
    cron.schedule('*/5 * * * *', () => {
      void this.recharger();
    });
  }

  async recharger(): Promise<void> {
    const sources = await this.catalogue.sources(true);
    const identifiantsActifs = new Set(sources.map((s) => s.id));

    for (const [id, tache] of this.taches) {
      if (!identifiantsActifs.has(id)) {
        tache.stop();
        this.taches.delete(id);
        this.logger.log(`Planification retirée pour la source ${id}`);
      }
    }

    for (const source of sources) {
      if (this.taches.has(source.id)) {
        continue;
      }
      if (!cron.validate(source.frequenceCron)) {
        this.logger.error(
          `Expression cron invalide pour « ${source.libelle} » : ${source.frequenceCron}`,
        );
        continue;
      }

      const tache = cron.schedule(source.frequenceCron, () => {
        void this.file
          .planifierScan({ sourceId: source.id, declencheur: 'cron' })
          .catch((erreur) =>
            this.logger.error(`Planification impossible : ${String(erreur)}`),
          );
      });

      this.taches.set(source.id, tache);
      this.logger.log(
        `Source « ${source.libelle} » planifiée (${source.frequenceCron})`,
      );
    }
  }

  onApplicationShutdown(): void {
    for (const tache of this.taches.values()) {
      tache.stop();
    }
    this.taches.clear();
  }
}
