import { Logger } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { Module } from '@nestjs/common';
import { AiModule } from './ai/ai.module';
import { AuditModule } from './audit/audit.module';
import { CatalogModule } from './catalog/catalog.module';
import { ConnectorsModule } from './connectors/connectors.module';
import { DatabaseModule } from './db/database.module';
import { QueueModule } from './scheduler/queue';
import { SchedulerModule } from './scheduler/scheduler.module';

/**
 * Point d'entrée de l'orchestrateur (conteneur `orchestrateur`).
 *
 * Même image que la passerelle, commande différente : il n'expose aucun port
 * HTTP et ne sert aucune requête. Il découvre, analyse et catalogue — pendant
 * que la passerelle garde sa latence de restitution.
 */
@Module({
  imports: [
    DatabaseModule,
    CatalogModule,
    AuditModule,
    AiModule,
    ConnectorsModule,
    QueueModule,
    SchedulerModule,
  ],
})
class OrchestrateurModule {}

async function demarrer(): Promise<void> {
  const contexte = await NestFactory.createApplicationContext(OrchestrateurModule, {
    logger: ['error', 'warn', 'log'],
  });
  contexte.enableShutdownHooks();
  new Logger('Orchestrateur').log('Orchestrateur démarré (cron + worker)');
}

void demarrer();
