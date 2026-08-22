import { Inject, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import * as bcrypt from 'bcryptjs';
import { Pool } from 'pg';
import { AuditService } from '../audit/audit.service';
import { ACTIONS_AUDIT } from '../common/types';
import { PG_POOL } from '../db/database.module';

export interface Jetons {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export const TTL_ACCES_SECONDES = 15 * 60; // 15 min
export const TTL_RAFRAICHISSEMENT_SECONDES = 8 * 60 * 60; // 8 h

@Injectable()
export class AuthService {
  private readonly logger = new Logger(AuthService.name);

  constructor(
    @Inject(PG_POOL) private readonly pool: Pool,
    private readonly jwt: JwtService,
    private readonly audit: AuditService,
  ) {}

  async authentifier(
    identifiant: string,
    motDePasse: string,
    adresseIp: string | null,
  ): Promise<Jetons> {
    const { rows } = await this.pool.query<{
      identifiant: string;
      mot_de_passe: string;
      role_code: string;
      actif: boolean;
    }>(
      `SELECT identifiant, mot_de_passe, role_code, actif
         FROM utilisateur WHERE identifiant = $1`,
      [identifiant],
    );

    const compte = rows[0];
    // La comparaison est faite même quand le compte n'existe pas, contre une
    // empreinte factice : sans cela le temps de réponse révèle quels
    // identifiants existent.
    const empreinteReference = compte?.mot_de_passe ?? '$2a$10$invalidinvalidinvalidinvalidinvalidinvalidinvalidinvalidinv';
    const motDePasseValide = await bcrypt.compare(motDePasse, empreinteReference);

    if (!compte || !compte.actif || !motDePasseValide) {
      await this.audit.append({
        utilisateurId: identifiant,
        roleEffectif: compte?.role_code ?? 'inconnu',
        action: ACTIONS_AUDIT.REFUS,
        politiqueAppliquee: 'refus',
        adresseIp,
        details: { motif: 'authentification_echouee' },
      });
      this.logger.warn(`Authentification refusée pour « ${identifiant} »`);
      throw new UnauthorizedException('Identifiants invalides');
    }

    await this.audit.append({
      utilisateurId: compte.identifiant,
      roleEffectif: compte.role_code,
      action: ACTIONS_AUDIT.AUTHENTIFICATION,
      adresseIp,
      details: { resultat: 'succes' },
    });

    return this.emettre(compte.identifiant, compte.role_code);
  }

  emettre(sujet: string, role: string): Jetons {
    return {
      accessToken: this.jwt.sign(
        { sub: sujet, role, type: 'acces' },
        { expiresIn: TTL_ACCES_SECONDES },
      ),
      refreshToken: this.jwt.sign(
        { sub: sujet, role, type: 'rafraichissement' },
        { expiresIn: TTL_RAFRAICHISSEMENT_SECONDES },
      ),
      expiresIn: TTL_ACCES_SECONDES,
    };
  }

  async rafraichir(refreshToken: string): Promise<Jetons> {
    let charge: { sub: string; role: string; type?: string };
    try {
      charge = this.jwt.verify(refreshToken);
    } catch {
      throw new UnauthorizedException('Jeton de rafraîchissement invalide');
    }

    if (charge.type !== 'rafraichissement') {
      throw new UnauthorizedException("Ce jeton n'est pas un jeton de rafraîchissement");
    }

    // Le rôle est relu en base : une révocation ou un changement de rôle prend
    // effet au rafraîchissement, sans attendre l'expiration du refresh.
    const { rows } = await this.pool.query<{ role_code: string; actif: boolean }>(
      'SELECT role_code, actif FROM utilisateur WHERE identifiant = $1',
      [charge.sub],
    );
    const compte = rows[0];
    if (!compte || !compte.actif) {
      throw new UnauthorizedException('Compte inconnu ou désactivé');
    }

    return this.emettre(charge.sub, compte.role_code);
  }
}
