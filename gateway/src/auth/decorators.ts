import {
  createParamDecorator,
  CustomDecorator,
  ExecutionContext,
  SetMetadata,
} from '@nestjs/common';
import { UtilisateurJwt } from '../common/types';

export const CLE_PUBLIC = 'route_publique';
export const CLE_ROLES = 'roles_autorises';

/** Marque une route accessible sans jeton (uniquement `/auth/token` et `/sante`). */
export const Public = (): CustomDecorator => SetMetadata(CLE_PUBLIC, true);

/** Restreint une route à une liste de rôles (contrôle en amont du PDP). */
export const Roles = (...roles: string[]): CustomDecorator =>
  SetMetadata(CLE_ROLES, roles);

/** Injecte l'utilisateur porté par le JWT validé. */
export const Utilisateur = createParamDecorator(
  (_donnees: unknown, contexte: ExecutionContext): UtilisateurJwt => {
    const requete = contexte.switchToHttp().getRequest();
    return requete.user as UtilisateurJwt;
  },
);
