import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  Logger,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { Observable } from 'rxjs';
import { AuthGuard } from '@nestjs/passport';
import { AuditService } from '../audit/audit.service';
import { ACTIONS_AUDIT, UtilisateurJwt } from '../common/types';
import { CLE_PUBLIC, CLE_ROLES } from './decorators';

/**
 * Garde d'authentification appliquée globalement.
 *
 * Elle est **globale** et non posée route par route : une route nouvelle est
 * protégée par défaut, on doit la déclarer publique explicitement. L'inverse
 * — protéger à la main — laisse tôt ou tard une route ouverte.
 */
@Injectable()
export class JwtAuthGuard extends AuthGuard('jwt') {
  constructor(private readonly reflector: Reflector) {
    super();
  }

  canActivate(contexte: ExecutionContext): boolean | Promise<boolean> | Observable<boolean> {
    const publique = this.reflector.getAllAndOverride<boolean>(CLE_PUBLIC, [
      contexte.getHandler(),
      contexte.getClass(),
    ]);
    if (publique) {
      return true;
    }
    return super.canActivate(contexte) as boolean | Promise<boolean> | Observable<boolean>;
  }
}

/**
 * Contrôle de rôle déclaratif, en amont du PDP.
 *
 * Il ne remplace pas `PolicyService` : il protège les routes d'administration
 * (déclencher un scan, déclarer une source), là où la décision ne dépend pas
 * du contenu d'un document. Toute décision liée à un document passe par le PDP.
 */
@Injectable()
export class RolesGuard implements CanActivate {
  private readonly logger = new Logger(RolesGuard.name);

  constructor(
    private readonly reflector: Reflector,
    private readonly audit: AuditService,
  ) {}

  async canActivate(contexte: ExecutionContext): Promise<boolean> {
    const rolesAutorises = this.reflector.getAllAndOverride<string[]>(CLE_ROLES, [
      contexte.getHandler(),
      contexte.getClass(),
    ]);

    if (!rolesAutorises || rolesAutorises.length === 0) {
      return true;
    }

    const requete = contexte.switchToHttp().getRequest();
    const utilisateur = requete.user as UtilisateurJwt | undefined;

    if (!utilisateur || !rolesAutorises.includes(utilisateur.role)) {
      // Un refus est un événement de sécurité : il se journalise au même titre
      // qu'un succès, sinon un attaquant qui sonde le système ne laisse aucune
      // trace (piège n°5).
      await this.audit.append({
        utilisateurId: utilisateur?.sub ?? 'anonyme',
        roleEffectif: utilisateur?.role ?? 'inconnu',
        action: ACTIONS_AUDIT.REFUS,
        politiqueAppliquee: 'refus',
        adresseIp: requete.ip ?? null,
        details: {
          motif: 'role_non_autorise',
          route: `${requete.method} ${requete.url}`,
          rolesAttendus: rolesAutorises,
        },
      });

      this.logger.warn(
        `Refus RBAC : ${utilisateur?.role ?? 'anonyme'} sur ${requete.method} ${requete.url}`,
      );
      throw new ForbiddenException('Rôle non autorisé pour cette opération');
    }

    return true;
  }
}
