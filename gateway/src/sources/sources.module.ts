import { Module } from '@nestjs/common';
import { QueueModule } from '../scheduler/queue';
import { SourcesController } from './sources.controller';

@Module({
  imports: [QueueModule],
  controllers: [SourcesController],
})
export class SourcesModule {}
