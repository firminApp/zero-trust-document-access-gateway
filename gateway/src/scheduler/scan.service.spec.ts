import { Test } from '@nestjs/testing';
import { AuditService } from '../audit/audit.service';
import { CatalogService } from '../catalog/catalog.service';
import { DocumentCatalogue, Source } from '../common/types';
import { ConnectorFactory } from '../connectors/connector.factory';
import { Ressource } from '../connectors/connector.interface';
import { PG_POOL } from '../db/database.module';
import { FileTaches } from './queue';
import { ScanService, TAILLE_LOT } from './scan.service';

/**
 * Critères d'acceptation M2 :
 *   - deuxième exécution sur une source inchangée : 0 document réanalysé ;
 *   - un fichier modifié est réanalysé au scan suivant ;
 *   - un fichier corrompu passe en échec sans faire tomber le lot.
 */

const SOURCE: Source = {
  id: 'src-1',
  type: 'local',
  libelle: 'Disque local',
  configuration: { chemin: '/data' },
  frequenceCron: '0 2 * * *',
  dernierScan: null,
  actif: true,
};

function ressource(cle: string): Ressource {
  return { cle, taille: 10, dateModification: new Date('2026-01-01') };
}

function document(id: string): DocumentCatalogue {
  return {
    id,
    sourceId: SOURCE.id,
    cheminSource: `${id}.txt`,
    empreinteSha256: 'a'.repeat(64),
    typeMime: 'text/plain',
    tailleOctets: 10,
    statut: 'decouvert',
    niveauMax: null,
    dateDecouverte: new Date(),
    dateAnalyse: null,
    tentatives: 0,
    motifEchec: null,
  };
}

describe('ScanService — scan incrémental', () => {
  let service: ScanService;
  let pool: { query: jest.Mock };
  let catalogue: {
    upsertDocument: jest.Mock;
    marquerScan: jest.Mock;
  };
  let connecteur: { lister: jest.Mock; lire: jest.Mock };
  let file: { planifierAnalyses: jest.Mock };
  let audit: { append: jest.Mock };

  function listerCes(cles: string[]): jest.Mock {
    return jest.fn(async function* (): AsyncIterable<Ressource> {
      for (const cle of cles) {
        yield ressource(cle);
      }
    });
  }

  beforeEach(async () => {
    pool = {
      query: jest.fn().mockResolvedValue({ rows: [{ id: 'exec-1' }], rowCount: 1 }),
    };
    catalogue = {
      upsertDocument: jest.fn().mockResolvedValue(null),
      marquerScan: jest.fn().mockResolvedValue(undefined),
    };
    connecteur = {
      lister: listerCes(['a.txt', 'b.txt']),
      lire: jest.fn().mockResolvedValue(Buffer.from('contenu')),
    };
    file = { planifierAnalyses: jest.fn().mockResolvedValue(undefined) };
    audit = { append: jest.fn().mockResolvedValue('audit-1') };

    const module = await Test.createTestingModule({
      providers: [
        ScanService,
        { provide: PG_POOL, useValue: pool },
        { provide: CatalogService, useValue: catalogue },
        {
          provide: ConnectorFactory,
          useValue: { pour: (): typeof connecteur => connecteur },
        },
        { provide: FileTaches, useValue: file },
        { provide: AuditService, useValue: audit },
      ],
    }).compile();

    service = module.get(ScanService);
  });

  it('catalogue les nouvelles ressources et les met en file', async () => {
    catalogue.upsertDocument
      .mockResolvedValueOnce(document('doc-a'))
      .mockResolvedValueOnce(document('doc-b'));

    const resultat = await service.scanner(SOURCE, 'manuel');

    expect(resultat).toMatchObject({ nbListes: 2, nbNouveaux: 2, nbInchanges: 0, nbEchecs: 0 });
    expect(file.planifierAnalyses).toHaveBeenCalledWith(['doc-a', 'doc-b']);
  });

  it("deuxième exécution sur une source inchangée : aucune analyse relancée", async () => {
    // `upsertDocument` rend null quand l'empreinte est identique : c'est ce
    // court-circuit qui rend le coût proportionnel aux nouveautés.
    catalogue.upsertDocument.mockResolvedValue(null);

    const resultat = await service.scanner(SOURCE, 'cron');

    expect(resultat).toMatchObject({ nbListes: 2, nbNouveaux: 0, nbInchanges: 2 });
    expect(file.planifierAnalyses).toHaveBeenCalledWith([]);
  });

  it('un fichier modifié est réanalysé', async () => {
    catalogue.upsertDocument
      .mockResolvedValueOnce(null)                 // inchangé
      .mockResolvedValueOnce(document('doc-b'));   // empreinte différente

    const resultat = await service.scanner(SOURCE, 'cron');

    expect(resultat).toMatchObject({ nbNouveaux: 1, nbInchanges: 1 });
    expect(file.planifierAnalyses).toHaveBeenCalledWith(['doc-b']);
  });

  it("un fichier illisible passe en échec sans interrompre le lot", async () => {
    connecteur.lister = listerCes(['bon1.txt', 'corrompu.txt', 'bon2.txt']);
    connecteur.lire.mockImplementation(async (cle: string) => {
      if (cle === 'corrompu.txt') {
        throw new Error('fichier illisible');
      }
      return Buffer.from('contenu');
    });
    catalogue.upsertDocument.mockImplementation(async (entree: { cheminSource: string }) =>
      document(entree.cheminSource),
    );

    const resultat = await service.scanner(SOURCE, 'cron');

    expect(resultat).toMatchObject({ nbListes: 3, nbNouveaux: 2, nbEchecs: 1 });
    expect(file.planifierAnalyses).toHaveBeenCalledWith(['bon1.txt', 'bon2.txt']);
  });

  it('met en file par lots de 200', async () => {
    const cles = Array.from({ length: TAILLE_LOT + 5 }, (_, i) => `f${i}.txt`);
    connecteur.lister = listerCes(cles);
    catalogue.upsertDocument.mockImplementation(async (entree: { cheminSource: string }) =>
      document(entree.cheminSource),
    );

    await service.scanner(SOURCE, 'cron');

    // Un lot plein pendant le parcours, puis le reliquat à la fin.
    expect(file.planifierAnalyses).toHaveBeenCalledTimes(2);
    expect(file.planifierAnalyses.mock.calls[0][0]).toHaveLength(TAILLE_LOT);
    expect(file.planifierAnalyses.mock.calls[1][0]).toHaveLength(5);
  });

  it('journalise le scan et horodate la source', async () => {
    await service.scanner(SOURCE, 'manuel');

    expect(catalogue.marquerScan).toHaveBeenCalledWith(SOURCE.id);
    expect(audit.append).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'SCAN' }),
    );
  });

  it("clôt l'exécution même si le parcours échoue", async () => {
    connecteur.lister = jest.fn(async function* (): AsyncIterable<Ressource> {
      yield ressource('a.txt');
      throw new Error('source coupée');
    });

    await expect(service.scanner(SOURCE, 'cron')).rejects.toThrow('source coupée');

    // `scan_execution` doit être refermée : sinon le tableau de bord affiche
    // indéfiniment un scan « en cours ».
    const clotures = pool.query.mock.calls.filter((appel) =>
      String(appel[0]).includes('UPDATE scan_execution'),
    );
    expect(clotures).toHaveLength(1);
  });

  // --- Reprise ---------------------------------------------------------------

  it('remet en file tout document non analysé, pas seulement les échecs', async () => {
    pool.query.mockResolvedValueOnce({ rows: [{ id: 'doc-1' }, { id: 'doc-2' }] });

    const nombre = await service.replanifierEnAttente(SOURCE.id);

    expect(nombre).toBe(2);
    expect(file.planifierAnalyses).toHaveBeenCalledWith(['doc-1', 'doc-2']);

    const sql = String(pool.query.mock.calls[0][0]);
    expect(sql).toContain("statut <> 'analyse'");
    expect(sql).toContain('tentatives <');
  });

  it('ne remet rien en file quand tout est analysé', async () => {
    pool.query.mockResolvedValueOnce({ rows: [] });
    expect(await service.replanifierEnAttente(SOURCE.id)).toBe(0);
    expect(file.planifierAnalyses).toHaveBeenCalledWith([]);
  });
});
