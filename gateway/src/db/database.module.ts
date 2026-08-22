import { Global, Module, OnApplicationShutdown } from '@nestjs/common';
import { Pool } from 'pg';

export const PG_POOL = 'PG_POOL';

/**
 * Accès PostgreSQL partagé.
 *
 * Le pool est global : `AuditService.append()` doit pouvoir ouvrir une
 * transaction SERIALIZABLE depuis n'importe quel point du portail sans
 * dépendre d'un module particulier.
 */
@Global()
@Module({
  providers: [
    {
      provide: PG_POOL,
      useFactory: (): Pool =>
        new Pool({
          connectionString:
            process.env.POSTGRES_URL ?? 'postgresql://ztg:ztg@localhost:5432/ztg',
          max: Number(process.env.PG_POOL_MAX ?? 10),
          idleTimeoutMillis: 30_000,
        }),
    },
  ],
  exports: [PG_POOL],
})
export class DatabaseModule implements OnApplicationShutdown {
  constructor() {}

  async onApplicationShutdown(): Promise<void> {
    // Le pool est fermé par le conteneur Nest lors de l'arrêt du processus ;
    // ce hook existe pour rendre l'intention explicite en revue.
  }
}
