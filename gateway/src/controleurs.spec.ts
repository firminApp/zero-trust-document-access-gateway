/**
 * Contrôleurs et services d'agrégation.
 *
 * Les contrôleurs sont volontairement minces : ils traduisent une requête HTTP
 * en appel de service et posent les en-têtes. Ce qui se teste ici, c'est
 * exactement cela — en particulier les en-têtes de politique, qui sont la
 * partie visible de la décision d'accès.
 */

import { AuditController } from './audit/audit.controller';
import { AuditService } from './audit/audit.service';
import { CatalogService } from './catalog/catalog.service';
import { DocumentsController } from './documents/documents.controller';
import { DocumentsService } from './documents/documents.service';
import { PolicyRepository } from './policy/policy.repository';
import { PolicyService } from './policy/policy.service';
import { SanteController } from './sante.controller';
import { FileTaches } from './scheduler/queue';
import { SourcesController } from './sources/sources.controller';
import { StatistiquesController } from './statistiques/statistiques.controller';
import { StatistiquesService } from './statistiques/statistiques.service';
import { AiClient } from './ai/ai.client';
import { Pool } from 'pg';

const UTILISATEUR = { sub: 'awa', role: 'conformite' };

describe('DocumentsController', () => {
  const restitution = {
    contenu: Buffer.from('contenu protégé'),
    typeMime: 'text/plain',
    politiqueAppliquee: 'masque' as const,
    niveauMax: 'moyen' as const,
    documentId: 'doc-1',
    auditId: '42',
    nomFichier: 'bail.txt',
  };

  function reponseSimulee(): Record<string, jest.Mock> {
    const reponse: Record<string, jest.Mock> = {};
    reponse.status = jest.fn().mockReturnValue(reponse);
    reponse.setHeader = jest.fn().mockReturnValue(reponse);
    reponse.send = jest.fn().mockReturnValue(reponse);
    return reponse;
  }

  it('pose les en-têtes de politique sur la réponse', async () => {
    const documents = { restituer: jest.fn().mockResolvedValue(restitution) };
    const controleur = new DocumentsController(
      documents as unknown as DocumentsService,
      {} as CatalogService,
    );
    const reponse = reponseSimulee();

    await controleur.contenu(
      'doc-1',
      UTILISATEUR,
      '10.0.0.1',
      reponse as never,
      'original',
    );

    expect(reponse.setHeader).toHaveBeenCalledWith('X-Politique-Appliquee', 'masque');
    expect(reponse.setHeader).toHaveBeenCalledWith('X-Niveau-Max-Detecte', 'moyen');
    expect(reponse.setHeader).toHaveBeenCalledWith('X-Document-Id', 'doc-1');
    expect(reponse.setHeader).toHaveBeenCalledWith('X-Audit-Id', '42');
    expect(reponse.send).toHaveBeenCalledWith(restitution.contenu);
  });

  it('ne retient que « texte » comme format alternatif', async () => {
    const documents = { restituer: jest.fn().mockResolvedValue(restitution) };
    const controleur = new DocumentsController(
      documents as unknown as DocumentsService,
      {} as CatalogService,
    );

    await controleur.contenu('doc-1', UTILISATEUR, '10.0.0.1', reponseSimulee() as never, 'zip');
    expect(documents.restituer).toHaveBeenCalledWith(
      'doc-1',
      expect.objectContaining({ format: 'original' }),
    );

    await controleur.contenu('doc-1', UTILISATEUR, '10.0.0.1', reponseSimulee() as never, 'texte');
    expect(documents.restituer).toHaveBeenLastCalledWith(
      'doc-1',
      expect.objectContaining({ format: 'texte' }),
    );
  });

  it('échappe les guillemets du nom de fichier', async () => {
    const documents = {
      restituer: jest.fn().mockResolvedValue({ ...restitution, nomFichier: 'a"b.txt' }),
    };
    const controleur = new DocumentsController(
      documents as unknown as DocumentsService,
      {} as CatalogService,
    );
    const reponse = reponseSimulee();

    await controleur.contenu('doc-1', UTILISATEUR, '10.0.0.1', reponse as never, undefined);

    expect(reponse.setHeader).toHaveBeenCalledWith(
      'Content-Disposition',
      'inline; filename="ab.txt"',
    );
  });

  it('transmet les filtres de listage au catalogue', async () => {
    const catalogue = { lister: jest.fn().mockResolvedValue({ total: 0, documents: [] }) };
    const controleur = new DocumentsController(
      {} as DocumentsService,
      catalogue as unknown as CatalogService,
    );

    await controleur.lister('src-1', 'analyse', 'critique', '2', '25');

    expect(catalogue.lister).toHaveBeenCalledWith({
      sourceId: 'src-1',
      statut: 'analyse',
      niveau: 'critique',
      page: 2,
      taille: 25,
    });
  });
});

describe('AuditController', () => {
  it('convertit les paramètres de pagination', async () => {
    const audit = { rechercher: jest.fn().mockResolvedValue({ total: 0, entrees: [] }) };
    const controleur = new AuditController(audit as unknown as AuditService);

    await controleur.rechercher('doc-1', 'awa', '2026-01-01', '2026-02-01', '3', '20');

    expect(audit.rechercher).toHaveBeenCalledWith({
      documentId: 'doc-1',
      utilisateurId: 'awa',
      depuis: '2026-01-01',
      jusqua: '2026-02-01',
      page: 3,
      taille: 20,
    });
  });

  it('expose la vérification de la chaîne', async () => {
    const audit = {
      verifyChain: jest.fn().mockResolvedValue({ intact: true, premiereRupture: null, nbEntrees: 5 }),
    };
    const controleur = new AuditController(audit as unknown as AuditService);

    expect(await controleur.verification()).toEqual({
      intact: true,
      premiereRupture: null,
      nbEntrees: 5,
    });
  });
});

describe('SourcesController', () => {
  const source = {
    id: 'src-1',
    type: 'local' as const,
    libelle: 'Disque',
    configuration: {},
    frequenceCron: '0 2 * * *',
    dernierScan: null,
    actif: true,
  };

  it('journalise la création de source comme CONFIG', async () => {
    const catalogue = { creerSource: jest.fn().mockResolvedValue(source) };
    const file = { planifierScan: jest.fn() };
    const audit = { append: jest.fn().mockResolvedValue('1') };
    const controleur = new SourcesController(
      catalogue as unknown as CatalogService,
      file as unknown as FileTaches,
      audit as unknown as AuditService,
    );

    await controleur.creer(
      { type: 'local', libelle: 'Disque', configuration: {} },
      { sub: 'admin', role: 'admin_systeme' },
      '10.0.0.1',
    );

    expect(audit.append).toHaveBeenCalledWith(expect.objectContaining({ action: 'CONFIG' }));
  });

  it('planifie un scan et le journalise', async () => {
    const catalogue = { source: jest.fn().mockResolvedValue(source) };
    const file = { planifierScan: jest.fn().mockResolvedValue(undefined) };
    const audit = { append: jest.fn().mockResolvedValue('1') };
    const controleur = new SourcesController(
      catalogue as unknown as CatalogService,
      file as unknown as FileTaches,
      audit as unknown as AuditService,
    );

    const resultat = await controleur.scanner(
      'src-1',
      { sub: 'admin', role: 'admin_systeme' },
      '10.0.0.1',
    );

    expect(resultat).toEqual({ planifie: true, sourceId: 'src-1' });
    expect(file.planifierScan).toHaveBeenCalledWith({
      sourceId: 'src-1',
      declencheur: 'manuel',
    });
    expect(audit.append).toHaveBeenCalledWith(expect.objectContaining({ action: 'SCAN' }));
  });

  it('journalise un refus pour une source inconnue et ne planifie rien', async () => {
    const catalogue = { source: jest.fn().mockResolvedValue(null) };
    const file = { planifierScan: jest.fn() };
    const audit = { append: jest.fn().mockResolvedValue('1') };
    const controleur = new SourcesController(
      catalogue as unknown as CatalogService,
      file as unknown as FileTaches,
      audit as unknown as AuditService,
    );

    const resultat = await controleur.scanner(
      'inconnue',
      { sub: 'admin', role: 'admin_systeme' },
      '10.0.0.1',
    );

    expect(resultat.planifie).toBe(false);
    expect(file.planifierScan).not.toHaveBeenCalled();
    expect(audit.append).toHaveBeenCalledWith(expect.objectContaining({ action: 'REFUS' }));
  });
});

describe('SanteController', () => {
  it('rapporte « ok » quand base et moteur répondent', async () => {
    const controleur = new SanteController(
      { query: jest.fn().mockResolvedValue({ rows: [] }) } as unknown as Pool,
      { sante: jest.fn().mockResolvedValue({ statut: 'ok' }) } as unknown as AiClient,
    );

    expect(await controleur.sante()).toEqual({ statut: 'ok', base: 'ok', moteurIa: 'ok' });
  });

  it('rapporte « degrade » quand la base est indisponible', async () => {
    const controleur = new SanteController(
      { query: jest.fn().mockRejectedValue(new Error('down')) } as unknown as Pool,
      { sante: jest.fn().mockResolvedValue({ statut: 'ok' }) } as unknown as AiClient,
    );

    expect(await controleur.sante()).toMatchObject({ statut: 'degrade', base: 'indisponible' });
  });

  it('reste « ok » si seul le moteur IA est indisponible', async () => {
    // Le portail peut encore refuser et journaliser : il n'est pas hors service.
    const controleur = new SanteController(
      { query: jest.fn().mockResolvedValue({ rows: [] }) } as unknown as Pool,
      { sante: jest.fn().mockRejectedValue(new Error('down')) } as unknown as AiClient,
    );

    expect(await controleur.sante()).toEqual({
      statut: 'ok',
      base: 'ok',
      moteurIa: 'indisponible',
    });
  });
});

describe('PolicyRepository', () => {
  it('convertit les lignes de la matrice', async () => {
    const pool = {
      query: jest.fn().mockResolvedValue({
        rows: [{ code: 'support_n1', niveau_sensibilite: 'moyen', action: 'masque' }],
      }),
    };
    const repository = new PolicyRepository(pool as unknown as Pool);

    expect(await repository.chargerMatrice()).toEqual([
      { roleCode: 'support_n1', niveau: 'moyen', action: 'masque' },
    ]);
  });

  it('liste les rôles connus', async () => {
    const pool = {
      query: jest.fn().mockResolvedValue({ rows: [{ code: 'conformite' }] }),
    };
    const repository = new PolicyRepository(pool as unknown as Pool);
    expect(await repository.rolesConnus()).toEqual(['conformite']);
  });
});

describe('PolicyService — démarrage dégradé', () => {
  it('démarre en refusant tout si la matrice est illisible', async () => {
    // Blocage circulaire à éviter : les migrations s'appliquent depuis cette
    // image, le service doit donc pouvoir démarrer sur une base non migrée —
    // mais en refusant tout.
    const repository = {
      chargerMatrice: jest.fn().mockRejectedValue(new Error('relation inexistante')),
    };
    const service = new PolicyService(repository as unknown as PolicyRepository);

    await service.onModuleInit();

    expect(service.decide('conformite', 'faible')).toBe('refus');
    service.onApplicationShutdown();
  });
});

describe('StatistiquesController', () => {
  it('expose la matrice de politique en vigueur', () => {
    const politique = {
      matriceComplete: jest
        .fn()
        .mockReturnValue([{ role: 'conformite', niveau: 'critique', action: 'complet' }]),
    };
    const controleur = new StatistiquesController(
      {} as StatistiquesService,
      politique as unknown as PolicyService,
    );

    expect(controleur.matrice().matrice).toHaveLength(1);
  });
});

describe('StatistiquesService', () => {
  it('agrège documents, entités, scans et audit', async () => {
    const reponses: Array<{ rows: Array<Record<string, unknown>> }> = [
      { rows: [{ statut: 'analyse', total: '8' }, { statut: 'echec', total: '2' }] },
      { rows: [{ niveau_max: 'critique', total: '5' }, { niveau_max: null, total: '5' }] },
      {
        rows: [
          { libelle: 'Disque', type: 'local', niveau_max: 'critique', total: '5' },
          { libelle: 'Disque', type: 'local', niveau_max: 'faible', total: '3' },
        ],
      },
      { rows: [{ type_entite: 'IBAN', niveau_sensibilite: 'critique', total: '4' }] },
      { rows: [{ methode: 'regle', total: '4' }] },
      {
        rows: [
          {
            libelle: 'Disque',
            demarre_le: new Date('2026-01-01'),
            termine_le: null,
            nb_listes: 10,
            nb_nouveaux: 2,
            nb_echecs: 0,
          },
        ],
      },
      { rows: [{ action: 'LECTURE', total: '6' }] },
      { rows: [{ politique_appliquee: 'masque', total: '3' }] },
    ];
    let index = 0;
    const pool = { query: jest.fn().mockImplementation(async () => reponses[index++]) };

    const service = new StatistiquesService(pool as unknown as Pool);
    const stats = await service.calculer();

    expect(stats.documents.total).toBe(10);
    expect(stats.documents.parNiveau).toEqual({ critique: 5, non_analyse: 5 });
    expect(stats.documents.parSource[0]).toMatchObject({ source: 'Disque', total: 8 });
    expect(stats.entites.total).toBe(4);
    expect(stats.audit.parAction).toEqual({ LECTURE: 6 });
    expect(stats.tauxEchec).toBe(0.2);
  });

  it('rend un taux d’échec nul sur un catalogue vide', async () => {
    const pool = { query: jest.fn().mockResolvedValue({ rows: [] }) };
    const stats = await new StatistiquesService(pool as unknown as Pool).calculer();

    expect(stats.documents.total).toBe(0);
    expect(stats.tauxEchec).toBe(0);
  });
});
