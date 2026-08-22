import { ForbiddenException, NotFoundException } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { AiClient } from '../ai/ai.client';
import { AuditService } from '../audit/audit.service';
import { CatalogService } from '../catalog/catalog.service';
import { LockedException } from '../common/locked.exception';
import { DocumentCatalogue, NiveauSens, StatutDoc } from '../common/types';
import { ConnectorFactory } from '../connectors/connector.factory';
import { SourceIndisponibleError } from '../connectors/connector.interface';
import { PolicyService } from '../policy/policy.service';
import { DocumentsService } from './documents.service';

/**
 * Séquence de restitution (M1) et T-03 : le nombre d'entrées d'audit doit
 * égaler le nombre de requêtes, **refus compris**.
 */

const SOURCE = {
  id: 'src-1',
  type: 'local' as const,
  libelle: 'Disque local',
  configuration: { chemin: '/data' },
  frequenceCron: '0 2 * * *',
  dernierScan: null,
  actif: true,
};

function document(surcharge: Partial<DocumentCatalogue> = {}): DocumentCatalogue {
  return {
    id: 'doc-1',
    sourceId: 'src-1',
    cheminSource: 'dossiers/contrat.pdf',
    empreinteSha256: 'a'.repeat(64),
    typeMime: 'application/pdf',
    tailleOctets: 1024,
    statut: 'analyse' as StatutDoc,
    niveauMax: 'moyen' as NiveauSens,
    dateDecouverte: new Date('2026-01-01'),
    dateAnalyse: new Date('2026-01-02'),
    tentatives: 0,
    motifEchec: null,
    ...surcharge,
  };
}

const CONTEXTE = {
  utilisateur: { sub: 'awa', role: 'support_n1' },
  adresseIp: '10.0.0.5',
  format: 'original' as const,
};

describe('DocumentsService — séquence de restitution', () => {
  let service: DocumentsService;
  let catalogue: jest.Mocked<Pick<CatalogService, 'document' | 'source' | 'enregistrerPseudonyme'>>;
  let audit: { append: jest.Mock };
  let politique: { decide: jest.Mock };
  let connecteur: { lire: jest.Mock };
  let ia: { proteger: jest.Mock };

  beforeEach(async () => {
    catalogue = {
      document: jest.fn().mockResolvedValue(document()),
      source: jest.fn().mockResolvedValue(SOURCE),
      enregistrerPseudonyme: jest.fn().mockResolvedValue(undefined),
    } as never;
    audit = { append: jest.fn().mockResolvedValue('audit-1') };
    politique = { decide: jest.fn().mockReturnValue('complet') };
    connecteur = { lire: jest.fn().mockResolvedValue(Buffer.from('contenu original')) };
    ia = {
      proteger: jest.fn().mockResolvedValue({
        contenu: Buffer.from('contenu protege'),
        nbEntitesProtegees: 3,
        typeMimeSortie: 'application/pdf',
        correspondances: [],
      }),
    };

    const module = await Test.createTestingModule({
      providers: [
        DocumentsService,
        { provide: CatalogService, useValue: catalogue },
        { provide: AuditService, useValue: audit },
        { provide: PolicyService, useValue: politique },
        {
          provide: ConnectorFactory,
          useValue: { pour: (): typeof connecteur => connecteur },
        },
        { provide: AiClient, useValue: ia },
      ],
    }).compile();

    service = module.get(DocumentsService);
  });

  // --- Cas nominal -----------------------------------------------------------

  it('restitue le contenu intégral quand la politique dit « complet »', async () => {
    const resultat = await service.restituer('doc-1', CONTEXTE);

    expect(resultat.contenu.toString()).toBe('contenu original');
    expect(resultat.politiqueAppliquee).toBe('complet');
    expect(resultat.niveauMax).toBe('moyen');
    expect(ia.proteger).not.toHaveBeenCalled();
  });

  it('appelle le moteur de protection quand la politique dit « masque »', async () => {
    politique.decide.mockReturnValue('masque');
    const resultat = await service.restituer('doc-1', CONTEXTE);

    expect(resultat.contenu.toString()).toBe('contenu protege');
    expect(resultat.politiqueAppliquee).toBe('masque');
    expect(ia.proteger).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'masque', niveauSeuil: 'moyen' }),
    );
  });

  it('persiste les correspondances de pseudonymisation, déjà chiffrées', async () => {
    politique.decide.mockReturnValue('pseudonymise');
    ia.proteger.mockResolvedValue({
      contenu: Buffer.from('x'),
      nbEntitesProtegees: 1,
      typeMimeSortie: 'text/plain',
      correspondances: [
        { empreinte: 'b'.repeat(64), jeton: 'PERS-4F2A', valeurChiffreeBase64: 'AAEC' },
      ],
    });

    await service.restituer('doc-1', CONTEXTE);

    expect(catalogue.enregistrerPseudonyme).toHaveBeenCalledWith({
      empreinte: 'b'.repeat(64),
      jeton: 'PERS-4F2A',
      valeurChiffreeBase64: 'AAEC',
    });
  });

  it('ignore une correspondance non chiffrable (AES_KEY absente)', async () => {
    politique.decide.mockReturnValue('pseudonymise');
    ia.proteger.mockResolvedValue({
      contenu: Buffer.from('x'),
      nbEntitesProtegees: 1,
      typeMimeSortie: 'text/plain',
      correspondances: [
        { empreinte: 'c'.repeat(64), jeton: 'PERS-1111', valeurChiffreeBase64: null },
      ],
    });

    await service.restituer('doc-1', CONTEXTE);
    expect(catalogue.enregistrerPseudonyme).not.toHaveBeenCalled();
  });

  // --- Refus et erreurs ------------------------------------------------------

  it('renvoie 404 pour un document inconnu', async () => {
    catalogue.document.mockResolvedValue(null);
    await expect(service.restituer('doc-x', CONTEXTE)).rejects.toBeInstanceOf(NotFoundException);
  });

  it.each(['decouvert', 'en_analyse', 'echec'] as StatutDoc[])(
    'renvoie 423 pour un document au statut %s, jamais le contenu',
    async (statut) => {
      catalogue.document.mockResolvedValue(document({ statut, niveauMax: null }));

      await expect(service.restituer('doc-1', CONTEXTE)).rejects.toBeInstanceOf(LockedException);
      expect(connecteur.lire).not.toHaveBeenCalled();
    },
  );

  it("renvoie 423 même si un niveau traîne sur un document non analysé", async () => {
    // Défense en profondeur : `statut` fait foi, pas `niveau_max`.
    catalogue.document.mockResolvedValue(document({ statut: 'decouvert', niveauMax: 'faible' }));
    await expect(service.restituer('doc-1', CONTEXTE)).rejects.toBeInstanceOf(LockedException);
    expect(politique.decide).not.toHaveBeenCalled();
  });

  it('renvoie 403 et ne lit pas la source quand la politique refuse', async () => {
    politique.decide.mockReturnValue('refus');

    await expect(service.restituer('doc-1', CONTEXTE)).rejects.toBeInstanceOf(ForbiddenException);
    expect(connecteur.lire).not.toHaveBeenCalled();
    expect(ia.proteger).not.toHaveBeenCalled();
  });

  it('renvoie 502 quand la source de stockage est indisponible', async () => {
    connecteur.lire.mockRejectedValue(new SourceIndisponibleError('s3://bucket'));
    await expect(service.restituer('doc-1', CONTEXTE)).rejects.toMatchObject({ status: 502 });
  });

  it('refuse de restituer si le moteur de protection est indisponible', async () => {
    // Refus par défaut : sans protection applicable, on ne rend rien en clair.
    politique.decide.mockReturnValue('masque');
    const { MoteurIaIndisponibleError } = await import('../ai/ai.client');
    ia.proteger.mockRejectedValue(new MoteurIaIndisponibleError('timeout'));

    await expect(service.restituer('doc-1', CONTEXTE)).rejects.toMatchObject({ status: 502 });
  });

  // --- T-03 : journalisation exhaustive --------------------------------------

  it('journalise le succès avec la politique appliquée', async () => {
    await service.restituer('doc-1', CONTEXTE);

    expect(audit.append).toHaveBeenCalledTimes(1);
    expect(audit.append).toHaveBeenCalledWith(
      expect.objectContaining({
        utilisateurId: 'awa',
        roleEffectif: 'support_n1',
        documentId: 'doc-1',
        action: 'LECTURE',
        politiqueAppliquee: 'complet',
        niveauEnCause: 'moyen',
        adresseIp: '10.0.0.5',
      }),
    );
  });

  it.each([
    [
      'document inconnu',
      (): void => {
        catalogue.document.mockResolvedValue(null);
      },
    ],
    [
      'document non analysé',
      (): void => {
        catalogue.document.mockResolvedValue(document({ statut: 'decouvert', niveauMax: null }));
      },
    ],
    [
      'politique de refus',
      (): void => {
        politique.decide.mockReturnValue('refus');
      },
    ],
    [
      'source indisponible',
      (): void => {
        connecteur.lire.mockRejectedValue(new SourceIndisponibleError('s3://bucket'));
      },
    ],
  ])('journalise aussi le refus : %s', async (_libelle, preparer) => {
    preparer();
    await expect(service.restituer('doc-1', CONTEXTE)).rejects.toBeDefined();

    expect(audit.append).toHaveBeenCalledTimes(1);
    expect(audit.append.mock.calls[0][0]).toMatchObject({ action: 'REFUS' });
  });

  it("écrit au journal AVANT de rendre le contenu", async () => {
    // Piège n°4 : si la journalisation suit la réponse, une coupure réseau
    // produit un accès non tracé. On vérifie donc que la promesse d'audit est
    // résolue avant que le service ne rende sa valeur.
    const ordre: string[] = [];
    audit.append.mockImplementation(async () => {
      ordre.push('audit');
      return 'audit-1';
    });

    await service.restituer('doc-1', CONTEXTE);
    ordre.push('reponse');

    expect(ordre).toEqual(['audit', 'reponse']);
  });

  it("ne journalise jamais de valeur d'entité", async () => {
    politique.decide.mockReturnValue('masque');
    await service.restituer('doc-1', CONTEXTE);

    const journalise = JSON.stringify(audit.append.mock.calls);
    expect(journalise).not.toContain('contenu original');
    expect(journalise).not.toContain('contenu protege');
  });

  // --- Métadonnées -----------------------------------------------------------

  it("les métadonnées ne contiennent aucune valeur d'entité", async () => {
    const catalogueEtendu = catalogue as unknown as { entitesDe: jest.Mock };
    catalogueEtendu.entitesDe = jest
      .fn()
      .mockResolvedValue([{ typeEntite: 'IBAN', niveau: 'critique', page: 1 }]);

    const resultat = await service.metadonnees('doc-1', {
      utilisateur: CONTEXTE.utilisateur,
      adresseIp: CONTEXTE.adresseIp,
    });

    expect(resultat.entites).toEqual([{ typeEntite: 'IBAN', niveau: 'critique', page: 1 }]);
    expect(JSON.stringify(resultat)).not.toMatch(/SN\d{2}[A-Z0-9]{20,}/);
  });

  it('journalise la consultation des métadonnées', async () => {
    (catalogue as unknown as { entitesDe: jest.Mock }).entitesDe = jest.fn().mockResolvedValue([]);
    await service.metadonnees('doc-1', {
      utilisateur: CONTEXTE.utilisateur,
      adresseIp: CONTEXTE.adresseIp,
    });
    expect(audit.append).toHaveBeenCalledTimes(1);
  });
});
