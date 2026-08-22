import { Module } from '@nestjs/common';
import { ConnectorsModule } from '../connectors/connectors.module';
import { QueueModule } from './queue';
import { ScanProcessor } from './scan.processor';
import { ScanService } from './scan.service';
import { SchedulerService } from './scheduler.service';

/**
 * Module de l'orchestrateur : cron + worker.
 *
 * Il n'est chargé que par `orchestrateur.ts`. La passerelle importe
 * `QueueModule` seul, pour pouvoir *émettre* un scan manuel sans héberger de
 * worker.
 */
@Module({
  imports: [ConnectorsModule, QueueModule],
  providers: [ScanService, ScanProcessor, SchedulerService],
  exports: [ScanService],
})
export class SchedulerModule {}
