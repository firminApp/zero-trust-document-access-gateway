import { Test } from '@nestjs/testing';
import { PG_POOL } from '../db/database.module';
import { AuditService } from './audit.service';

/**
 * Persistance du journal : transaction SERIALIZABLE, reprise sur conflit,
 * et rejeu du chaînage par lots.
 *
 * Le pool PostgreSQL est simulé : ce qui est vérifié ici, ce sont les
 * décisions du service — le niveau d'isolation demandé, le ROLLBACK en cas
 * d'échec, la reprise sur 40001. Le comportement réel des règles SQL est
 * couvert par T-04.
 */

interface ClientSimule {
  query: jest.Mock;
  release: jest.Mock;
}

function creerClient(): ClientSimule {
  return {
    query: jest.fn().mockImplementation(async (sql: string) => {
      if (String(sql).startsWith('SELECT empreinte')) {
        return { rows: [] };
      }
      if (String(sql).includes('INSERT INTO journal_audit')) {
        return { rows: [{ id: '1' }] };
      }
      return { rows: [] };
    }),
    release: jest.fn(),
  };
}

describe('AuditService — persistance', () => {
  let service: AuditService;
  let pool: { connect: jest.Mock; query: jest.Mock };
  let client: ClientSimule;

  const entree = {
    utilisateurId: 'awa',
    roleEffectif: 'conformite',
    documentId: 'doc-1',
    action: 'LECTURE',
    politiqueAppliquee: 'complet' as const,
    adresseIp: '10.0.0.1',
  };

  beforeEach(async () => {
    client = creerClient();
    pool = {
      connect: jest.fn().mockResolvedValue(client),
      query: jest.fn().mockResolvedValue({ rows: [] }),
    };

    const module = await Test.createTestingModule({
      providers: [AuditService, { provide: PG_POOL, useValue: pool }],
    }).compile();

    service = module.get(AuditService);
  });

  it('ouvre une transaction SERIALIZABLE', async () => {
    await service.append(entree);

    // Piège n°7 : sans sérialisation, deux insertions concurrentes lisent la
    // même empreinte précédente et produisent deux maillons frères.
    expect(client.query).toHaveBeenCalledWith('BEGIN ISOLATION LEVEL SERIALIZABLE');
    expect(client.query).toHaveBeenCalledWith('COMMIT');
  });

  it('chaîne sur la dernière empreinte connue', async () => {
    const precedente = 'b'.repeat(64);
    client.query.mockImplementation(async (sql: string) => {
      if (String(sql).startsWith('SELECT empreinte')) {
        return { rows: [{ empreinte: precedente }] };
      }
      if (String(sql).includes('INSERT INTO journal_audit')) {
        return { rows: [{ id: '2' }] };
      }
      return { rows: [] };
    });

    await service.append(entree);

    const insertion = client.query.mock.calls.find((appel) =>
      String(appel[0]).includes('INSERT INTO journal_audit'),
    );
    const valeurs = insertion?.[1] as unknown[];
    expect(valeurs[9]).toBe(precedente);          // empreinte_precedente
    expect(valeurs[10]).toMatch(/^[0-9a-f]{64}$/); // empreinte
  });

  it('ancre le premier maillon sur une empreinte précédente nulle', async () => {
    await service.append(entree);
    const insertion = client.query.mock.calls.find((appel) =>
      String(appel[0]).includes('INSERT INTO journal_audit'),
    );
    expect((insertion?.[1] as unknown[])[9]).toBeNull();
  });

  it('rejoue la transaction sur échec de sérialisation (40001)', async () => {
    let tentative = 0;
    pool.connect.mockImplementation(async () => {
      tentative += 1;
      if (tentative === 1) {
        const perdant = creerClient();
        perdant.query.mockImplementation(async (sql: string) => {
          if (String(sql).includes('INSERT INTO journal_audit')) {
            throw Object.assign(new Error('could not serialize access'), { code: '40001' });
          }
          return { rows: [] };
        });
        return perdant;
      }
      return client;
    });

    await expect(service.append(entree)).resolves.toBe('1');
    expect(tentative).toBe(2);
  });

  it('remonte une erreur qui n’est pas un conflit de sérialisation', async () => {
    client.query.mockImplementation(async (sql: string) => {
      if (String(sql).includes('INSERT INTO journal_audit')) {
        throw Object.assign(new Error('colonne inconnue'), { code: '42703' });
      }
      return { rows: [] };
    });

    await expect(service.append(entree)).rejects.toThrow('colonne inconnue');
    expect(client.query).toHaveBeenCalledWith('ROLLBACK');
  });

  it('libère toujours le client', async () => {
    await service.append(entree);
    expect(client.release).toHaveBeenCalled();
  });

  it("sérialise les détails en JSON et n'y met aucune valeur d'entité", async () => {
    await service.append({ ...entree, details: { motif: 'politique_refus' } });
    const insertion = client.query.mock.calls.find((appel) =>
      String(appel[0]).includes('INSERT INTO journal_audit'),
    );
    expect((insertion?.[1] as unknown[])[8]).toBe('{"motif":"politique_refus"}');
  });

  // --- verifyChain -----------------------------------------------------------

  function maillon(
    id: string,
    precedente: string | null,
    surcharge: Record<string, unknown> = {},
  ): Record<string, unknown> {
    const base = {
      id,
      horodatage: new Date(`2026-01-0${id}T00:00:00.000Z`),
      utilisateur_id: 'awa',
      role_effectif: 'conformite',
      document_id: 'doc-1',
      action: 'LECTURE',
      politique_appliquee: 'complet',
    };
    const empreinte = AuditService.calculerEmpreinte({
      empreintePrecedente: precedente,
      utilisateurId: base.utilisateur_id,
      roleEffectif: base.role_effectif,
      documentId: base.document_id,
      action: base.action,
      politiqueAppliquee: base.politique_appliquee,
      horodatageIso: base.horodatage.toISOString(),
    });
    return { ...base, empreinte_precedente: precedente, empreinte, ...surcharge };
  }

  it('valide une chaîne intacte lue en base', async () => {
    const un = maillon('1', null);
    const deux = maillon('2', un.empreinte as string);
    pool.query
      .mockResolvedValueOnce({ rows: [un, deux] })
      .mockResolvedValueOnce({ rows: [] });

    expect(await service.verifyChain()).toEqual({
      intact: true,
      premiereRupture: null,
      nbEntrees: 2,
    });
  });

  it('détecte une empreinte recalculée incohérente', async () => {
    const un = maillon('1', null);
    const deux = maillon('2', un.empreinte as string, { role_effectif: 'support_n1' });
    pool.query
      .mockResolvedValueOnce({ rows: [un, deux] })
      .mockResolvedValueOnce({ rows: [] });

    expect(await service.verifyChain()).toMatchObject({
      intact: false,
      premiereRupture: '2',
    });
  });

  it('détecte un maillon qui ne pointe pas vers son prédécesseur', async () => {
    const un = maillon('1', null);
    const deux = maillon('2', 'c'.repeat(64));
    pool.query
      .mockResolvedValueOnce({ rows: [un, deux] })
      .mockResolvedValueOnce({ rows: [] });

    expect(await service.verifyChain()).toMatchObject({ intact: false, premiereRupture: '2' });
  });

  it('considère un journal vide comme intact', async () => {
    pool.query.mockResolvedValueOnce({ rows: [] });
    expect(await service.verifyChain()).toEqual({
      intact: true,
      premiereRupture: null,
      nbEntrees: 0,
    });
  });

  // --- Recherche -------------------------------------------------------------

  it('compose les filtres de recherche', async () => {
    pool.query
      .mockResolvedValueOnce({ rows: [{ total: '3' }] })
      .mockResolvedValueOnce({ rows: [] });

    await service.rechercher({ documentId: 'doc-1', utilisateurId: 'awa', page: 2, taille: 10 });

    const sql = String(pool.query.mock.calls[1][0]);
    expect(sql).toContain('document_id = $1');
    expect(sql).toContain('utilisateur_id = $2');
    expect(sql).toContain('OFFSET');
  });

  it('borne la taille de page', async () => {
    pool.query
      .mockResolvedValueOnce({ rows: [{ total: '0' }] })
      .mockResolvedValueOnce({ rows: [] });

    await service.rechercher({ taille: 100_000 });

    const valeurs = pool.query.mock.calls[1][1] as number[];
    expect(valeurs[0]).toBe(500);
  });
});
