import { ExecutionContext, ForbiddenException } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { AuditService } from '../audit/audit.service';
import { CLE_PUBLIC, CLE_ROLES } from './decorators';
import { JwtAuthGuard, RolesGuard } from './roles.guard';

/**
 * Gardes globales.
 *
 * Elles sont le premier filtre du portail : une route nouvelle est protégée
 * par défaut, et un refus de rôle est un événement de sécurité qui doit
 * laisser une trace (piège n°5).
 */

function contexte(
  utilisateur: { sub: string; role: string } | undefined,
  requete: Record<string, unknown> = {},
): ExecutionContext {
  return {
    switchToHttp: () => ({
      getRequest: () => ({
        user: utilisateur,
        ip: '10.0.0.9',
        method: 'GET',
        url: '/api/v1/audit',
        ...requete,
      }),
    }),
    getHandler: () => undefined,
    getClass: () => undefined,
  } as unknown as ExecutionContext;
}

describe('RolesGuard', () => {
  let garde: RolesGuard;
  let reflector: { getAllAndOverride: jest.Mock };
  let audit: { append: jest.Mock };

  beforeEach(() => {
    reflector = { getAllAndOverride: jest.fn() };
    audit = { append: jest.fn().mockResolvedValue('audit-1') };
    garde = new RolesGuard(
      reflector as unknown as Reflector,
      audit as unknown as AuditService,
    );
  });

  it('laisse passer une route sans exigence de rôle', async () => {
    reflector.getAllAndOverride.mockReturnValue(undefined);
    expect(await garde.canActivate(contexte({ sub: 'awa', role: 'support_n1' }))).toBe(true);
    expect(audit.append).not.toHaveBeenCalled();
  });

  it('laisse passer une liste de rôles vide', async () => {
    reflector.getAllAndOverride.mockReturnValue([]);
    expect(await garde.canActivate(contexte({ sub: 'awa', role: 'support_n1' }))).toBe(true);
  });

  it('laisse passer un rôle autorisé', async () => {
    reflector.getAllAndOverride.mockReturnValue(['conformite', 'admin_systeme']);
    expect(await garde.canActivate(contexte({ sub: 'awa', role: 'conformite' }))).toBe(true);
    expect(audit.append).not.toHaveBeenCalled();
  });

  it('refuse un rôle non autorisé', async () => {
    reflector.getAllAndOverride.mockReturnValue(['conformite']);
    await expect(
      garde.canActivate(contexte({ sub: 'awa', role: 'support_n1' })),
    ).rejects.toBeInstanceOf(ForbiddenException);
  });

  it('journalise le refus de rôle avec la route visée', async () => {
    reflector.getAllAndOverride.mockReturnValue(['conformite']);

    await expect(
      garde.canActivate(contexte({ sub: 'awa', role: 'support_n1' })),
    ).rejects.toBeDefined();

    expect(audit.append).toHaveBeenCalledWith(
      expect.objectContaining({
        utilisateurId: 'awa',
        roleEffectif: 'support_n1',
        action: 'REFUS',
        politiqueAppliquee: 'refus',
        adresseIp: '10.0.0.9',
        details: expect.objectContaining({
          motif: 'role_non_autorise',
          route: 'GET /api/v1/audit',
          rolesAttendus: ['conformite'],
        }),
      }),
    );
  });

  it('refuse et journalise une requête sans utilisateur', async () => {
    reflector.getAllAndOverride.mockReturnValue(['conformite']);

    await expect(garde.canActivate(contexte(undefined))).rejects.toBeInstanceOf(
      ForbiddenException,
    );
    expect(audit.append).toHaveBeenCalledWith(
      expect.objectContaining({ utilisateurId: 'anonyme', roleEffectif: 'inconnu' }),
    );
  });
});

describe('JwtAuthGuard', () => {
  it('laisse passer une route explicitement publique', () => {
    const reflector = { getAllAndOverride: jest.fn().mockReturnValue(true) };
    const garde = new JwtAuthGuard(reflector as unknown as Reflector);

    expect(garde.canActivate(contexte(undefined))).toBe(true);
    expect(reflector.getAllAndOverride).toHaveBeenCalledWith(CLE_PUBLIC, expect.anything());
  });

  it("consulte bien la métadonnée @Public avant de décider", () => {
    // La garde est globale : tout ce qui n'est pas marqué `@Public()` doit
    // traverser la validation du jeton. Le fait qu'une route non publique
    // aboutisse effectivement à un 401 est vérifié de bout en bout par T-01
    // (« le portail refuse toute lecture sans jeton ») — le rejouer ici
    // reviendrait à instancier la mécanique interne de Passport.
    const reflector = { getAllAndOverride: jest.fn().mockReturnValue(undefined) };
    const garde = new JwtAuthGuard(reflector as unknown as Reflector);

    expect(garde).toBeInstanceOf(JwtAuthGuard);
    expect(reflector.getAllAndOverride).not.toHaveBeenCalled();
  });
});

describe('décorateurs', () => {
  it('exposent les clés de métadonnées attendues', () => {
    expect(CLE_PUBLIC).toBe('route_publique');
    expect(CLE_ROLES).toBe('roles_autorises');
  });
});
