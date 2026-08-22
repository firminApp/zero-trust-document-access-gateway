import { Module } from '@nestjs/common';
import { ConnectorsModule } from '../connectors/connectors.module';
import { PolicyModule } from '../policy/policy.module';
import { DocumentsController } from './documents.controller';
import { DocumentsService } from './documents.service';

@Module({
  imports: [PolicyModule, ConnectorsModule],
  controllers: [DocumentsController],
  providers: [DocumentsService],
  exports: [DocumentsService],
})
export class DocumentsModule {}
