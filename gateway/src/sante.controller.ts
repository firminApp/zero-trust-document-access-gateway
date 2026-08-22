import { Controller, Get, Inject } from '@nestjs/common';
import { Pool } from 'pg';
import { AiClient } from './ai/ai.client';
import { Public } from './auth/decorators';
import { PG_POOL } from './db/database.module';

@Controller()
export class SanteController {
  constructor(
    @Inject(PG_POOL) private readonly pool: Pool,
    private readonly ia: AiClient,
  ) {}

  /** Sonde de disponibilité — publique, ne révèle aucune donnée métier. */
  @Public()
  @Get('sante')
  async sante(): Promise<{ statut: string; base: string; moteurIa: string }> {
    const base = await this.pool
      .query('SELECT 1')
      .then(() => 'ok')
      .catch(() => 'indisponible');

    const moteurIa = await this.ia
      .sante()
      .then((r) => r.statut)
      .catch(() => 'indisponible');

    return { statut: base === 'ok' ? 'ok' : 'degrade', base, moteurIa };
  }
}
