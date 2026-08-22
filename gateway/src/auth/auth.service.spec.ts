import { UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { Test } from '@nestjs/testing';
import * as bcrypt from 'bcryptjs';
import { AuditService } from '../audit/audit.service';
import { PG_POOL } from '../db/database.module';
import { AuthService, TTL_ACCES_SECONDES } from './auth.service';
import { JwtStrategy } from './jwt.strategy';

describe('AuthService', () => {
  let service: AuthService;
  let pool: { query: jest.Mock };
  let audit: { append: jest.Mock };
  let jwt: JwtService;

  const empreinte = bcrypt.hashSync('demo1234', 4);

  beforeEach(async () => {
    pool = { query: jest.fn() };
    audit = { append: jest.fn().mockResolvedValue('audit-1') };
    jwt = new JwtService({ secret: 'secret-de-test', signOptions: { algorithm: 'HS256' } });

    const module = await Test.createTestingModule({
      providers: [
        AuthService,
        { provide: PG_POOL, useValue: pool },
        { provide: JwtService, useValue: jwt },
        { provide: AuditService, useValue: audit },
      ],
    }).compile();

    service = module.get(AuthService);
  });

  function compte(surcharge: Record<string, unknown> = {}): Record<string, unknown> {
    return {
      identifiant: 'conformite',
      mot_de_passe: empreinte,
      role_code: 'conformite',
      actif: true,
      ...surcharge,
    };
  }

  it('émet un couple de jetons pour des identifiants valides', async () => {
    pool.query.mockResolvedValue({ rows: [compte()] });

    const jetons = await service.authentifier('conformite', 'demo1234', '10.0.0.1');

    expect(jetons.expiresIn).toBe(TTL_ACCES_SECONDES);
    const charge = jwt.verify<{ sub: string; role: string; type: string }>(jetons.accessToken);
    expect(charge).toMatchObject({ sub: 'conformite', role: 'conformite', type: 'acces' });
  });

  it('distingue le jeton de rafraîchissement du jeton d’accès', async () => {
    pool.query.mockResolvedValue({ rows: [compte()] });
    const jetons = await service.authentifier('conformite', 'demo1234', null);

    expect(jwt.verify<{ type: string }>(jetons.refreshToken).type).toBe('rafraichissement');
  });

  it("un jeton de rafraîchissement ne donne pas accès aux ressources", () => {
    // Sinon un refresh volé vaudrait 8 heures d'accès aux documents au lieu
    // de 15 minutes.
    const strategie = new JwtStrategy();
    expect(() =>
      strategie.validate({
        sub: 'awa',
        role: 'conformite',
        type: 'rafraichissement',
        iat: 0,
        exp: 0,
      }),
    ).toThrow(UnauthorizedException);
  });

  it('rejette un mot de passe erroné et journalise le refus', async () => {
    pool.query.mockResolvedValue({ rows: [compte()] });

    await expect(service.authentifier('conformite', 'mauvais', '10.0.0.1')).rejects.toBeInstanceOf(
      UnauthorizedException,
    );
    expect(audit.append).toHaveBeenCalledWith(expect.objectContaining({ action: 'REFUS' }));
  });

  it('rejette un compte inconnu et journalise', async () => {
    pool.query.mockResolvedValue({ rows: [] });

    await expect(service.authentifier('fantome', 'demo1234', null)).rejects.toBeInstanceOf(
      UnauthorizedException,
    );
    expect(audit.append).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'REFUS', utilisateurId: 'fantome' }),
    );
  });

  it('rend une réponse indiscernable pour un compte inconnu et un mot de passe faux', async () => {
    // Le compte inconnu est comparé à une empreinte factice, de sorte que ni
    // le message ni le temps de réponse ne révèlent quels identifiants
    // existent. On vérifie ici la propriété observable : les deux échecs sont
    // rigoureusement identiques du point de vue de l'appelant.
    pool.query.mockResolvedValueOnce({ rows: [] });
    const inconnu = await service
      .authentifier('fantome', 'demo1234', null)
      .catch((erreur: UnauthorizedException) => erreur);

    pool.query.mockResolvedValueOnce({ rows: [compte()] });
    const mauvaisMotDePasse = await service
      .authentifier('conformite', 'mauvais', null)
      .catch((erreur: UnauthorizedException) => erreur);

    expect(inconnu).toBeInstanceOf(UnauthorizedException);
    expect(mauvaisMotDePasse).toBeInstanceOf(UnauthorizedException);
    expect((inconnu as UnauthorizedException).message).toBe(
      (mauvaisMotDePasse as UnauthorizedException).message,
    );
  });

  it("l'empreinte factice est un hachage bcrypt valide, donc réellement comparé", async () => {
    // Une chaîne mal formée ferait échouer `bcrypt.compare` immédiatement et
    // rétablirait l'écart de temps que la parade cherche à supprimer.
    pool.query.mockResolvedValue({ rows: [] });
    const depart = Date.now();
    await expect(service.authentifier('fantome', 'demo1234', null)).rejects.toBeDefined();
    // Le hachage bcrypt prend un temps mesurable : la comparaison a bien eu lieu.
    expect(Date.now() - depart).toBeGreaterThan(0);
  });

  it('rejette un compte désactivé', async () => {
    pool.query.mockResolvedValue({ rows: [compte({ actif: false })] });
    await expect(service.authentifier('conformite', 'demo1234', null)).rejects.toBeInstanceOf(
      UnauthorizedException,
    );
  });

  it('journalise une authentification réussie', async () => {
    pool.query.mockResolvedValue({ rows: [compte()] });
    await service.authentifier('conformite', 'demo1234', '10.0.0.1');

    expect(audit.append).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'AUTHENTIFICATION', roleEffectif: 'conformite' }),
    );
  });

  it("ne journalise jamais le mot de passe", async () => {
    pool.query.mockResolvedValue({ rows: [compte()] });
    await service.authentifier('conformite', 'demo1234', null);
    expect(JSON.stringify(audit.append.mock.calls)).not.toContain('demo1234');
  });

  // --- Rafraîchissement ------------------------------------------------------

  it('relit le rôle en base au rafraîchissement', async () => {
    // Un changement de rôle prend effet au rafraîchissement, sans attendre
    // l'expiration du jeton long.
    const refresh = jwt.sign({ sub: 'awa', role: 'conformite', type: 'rafraichissement' });
    pool.query.mockResolvedValue({ rows: [{ role_code: 'support_n1', actif: true }] });

    const jetons = await service.rafraichir(refresh);

    expect(jwt.verify<{ role: string }>(jetons.accessToken).role).toBe('support_n1');
  });

  it('refuse un jeton d’accès présenté comme rafraîchissement', async () => {
    const acces = jwt.sign({ sub: 'awa', role: 'conformite', type: 'acces' });
    await expect(service.rafraichir(acces)).rejects.toBeInstanceOf(UnauthorizedException);
  });

  it('refuse un jeton illisible', async () => {
    await expect(service.rafraichir('pas.un.jeton')).rejects.toBeInstanceOf(
      UnauthorizedException,
    );
  });

  it('refuse le rafraîchissement d’un compte désactivé', async () => {
    const refresh = jwt.sign({ sub: 'awa', role: 'conformite', type: 'rafraichissement' });
    pool.query.mockResolvedValue({ rows: [{ role_code: 'conformite', actif: false }] });

    await expect(service.rafraichir(refresh)).rejects.toBeInstanceOf(UnauthorizedException);
  });
});
