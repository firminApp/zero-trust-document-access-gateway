import { Inject, Injectable, Logger } from '@nestjs/common';
import { Pool } from 'pg';
import { PG_POOL } from '../db/database.module';
import { ActionAcces, NiveauSens } from '../common/types';

export interface LignePolitique {
  roleCode: string;
  niveau: NiveauSens;
  action: ActionAcces;
}

/** Lecture de la matrice `politique_acces`. Aucune écriture depuis le portail. */
@Injectable()
export class PolicyRepository {
  private readonly logger = new Logger(PolicyRepository.name);

  constructor(@Inject(PG_POOL) private readonly pool: Pool) {}

  async chargerMatrice(): Promise<LignePolitique[]> {
    const { rows } = await this.pool.query<{
      code: string;
      niveau_sensibilite: NiveauSens;
      action: ActionAcces;
    }>(
      `SELECT r.code, p.niveau_sensibilite, p.action
         FROM politique_acces p
         JOIN role r ON r.id = p.role_id
        ORDER BY r.code, p.niveau_sensibilite`,
    );

    this.logger.log(`Matrice de politique chargée : ${rows.length} case(s)`);
    return rows.map((ligne) => ({
      roleCode: ligne.code,
      niveau: ligne.niveau_sensibilite,
      action: ligne.action,
    }));
  }

  async rolesConnus(): Promise<string[]> {
    const { rows } = await this.pool.query<{ code: string }>('SELECT code FROM role');
    return rows.map((r) => r.code);
  }
}
