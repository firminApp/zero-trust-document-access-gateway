import { HttpException } from '@nestjs/common';

/** 423 Locked (RFC 4918) — absent de l'enum `HttpStatus` de Nest. */
export const HTTP_LOCKED = 423;

/**
 * HTTP 423 — le document est au catalogue mais pas encore analysé.
 *
 * Nest ne fournit pas cette exception : elle est définie ici parce que le code
 * 423 porte une décision de conception, pas un détail technique. Le système ne
 * sait pas ce que contient le document ; la politique est donc inapplicable et
 * la seule réponse compatible avec le refus par défaut est de ne rien rendre
 * (ADR n°8). Servir le document « en attendant » recréerait exactement la
 * faille que le projet supprime.
 */
export class LockedException extends HttpException {
  constructor(message = "Document découvert mais non encore analysé : réessayer plus tard") {
    super(
      { statusCode: HTTP_LOCKED, message, error: 'Locked' },
      HTTP_LOCKED,
    );
  }
}
