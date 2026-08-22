import { Injectable, UnauthorizedException } from '@nestjs/common';
import { PassportStrategy } from '@nestjs/passport';
import { ExtractJwt, Strategy } from 'passport-jwt';
import { UtilisateurJwt } from '../common/types';

export interface ChargeUtileJwt {
  sub: string;
  role: string;
  type?: 'acces' | 'rafraichissement';
  iat: number;
  exp: number;
}

/**
 * Validation du jeton d'accès.
 *
 * Un jeton de rafraîchissement présenté comme jeton d'accès est rejeté :
 * sans cette vérification, un refresh volé donnerait 8 heures d'accès aux
 * documents au lieu de 15 minutes.
 */
@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy, 'jwt') {
  constructor() {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      ignoreExpiration: false,
      secretOrKey: process.env.JWT_SECRET ?? 'change-me',
    });
  }

  validate(charge: ChargeUtileJwt): UtilisateurJwt {
    if (charge.type === 'rafraichissement') {
      throw new UnauthorizedException(
        "Un jeton de rafraîchissement ne donne pas accès aux ressources",
      );
    }
    if (!charge.sub || !charge.role) {
      throw new UnauthorizedException('Jeton incomplet');
    }
    return { sub: charge.sub, role: charge.role };
  }
}
