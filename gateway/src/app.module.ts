import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { APP_GUARD } from '@nestjs/core';
import { AiModule } from './ai/ai.module';
import { AuditModule } from './audit/audit.module';
import { AuthModule } from './auth/auth.module';
import { JwtAuthGuard, RolesGuard } from './auth/roles.guard';
import { CatalogModule } from './catalog/catalog.module';
import { ConnectorsModule } from './connectors/connectors.module';
import { DatabaseModule } from './db/database.module';
import { DocumentsModule } from './documents/documents.module';
import { PolicyModule } from './policy/policy.module';
import { QueueModule } from './scheduler/queue';
import { SanteController } from './sante.controller';
import { SourcesModule } from './sources/sources.module';
import { StatistiquesModule } from './statistiques/statistiques.module';

/**
 * Portail d'accès (PEP).
 *
 * Les deux gardes sont enregistrées **globalement** et dans cet ordre :
 * authentification d'abord, rôle ensuite. Une route nouvelle est donc protégée
 * sans que personne ait à y penser ; l'ouvrir demande un `@Public()` explicite,
 * qui se voit en revue de code. L'inverse — protéger route par route — finit
 * toujours par laisser une porte ouverte.
 */
@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    DatabaseModule,
    CatalogModule,
    AuditModule,
    AiModule,
    QueueModule,
    AuthModule,
    PolicyModule,
    ConnectorsModule,
    DocumentsModule,
    SourcesModule,
    StatistiquesModule,
  ],
  controllers: [SanteController],
  providers: [
    { provide: APP_GUARD, useClass: JwtAuthGuard },
    { provide: APP_GUARD, useClass: RolesGuard },
  ],
})
export class AppModule {}
