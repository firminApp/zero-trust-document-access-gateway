import { Test } from '@nestjs/testing';
import { EntiteAnalysee } from '../common/types';
import { PG_POOL } from '../db/database.module';
import { CatalogService } from './catalog.service';

/**
 * Persistance du catalogue.
 *
 * Le test central est `enregistrerEntites` : c'est le point où les valeurs en
 * clair reçues du moteur IA doivent être hachées, et nulle part ailleurs.
 */

function ligneDocument(surcharge: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'doc-1',
    source_id: 'src-1',
    chemin_source: 'contrats/bail.pdf',
    empreinte_sha256: 'a'.repeat(64),
    type_mime: 'application/pdf',
    taille_octets: '2048',
    statut: 'analyse',
    niveau_max: 'critique',
    date_decouverte: new Date('2026-01-01'),
    date_analyse: new Date('2026-01-02'),
    tentatives: 0,
    motif_echec: null,
    ...surcharge,
  };
}

describe('CatalogService — persistance', () => {
  let service: CatalogService;
  let pool: { query: jest.Mock; connect: jest.Mock };
  let client: { query: jest.Mock; release: jest.Mock };

  beforeEach(async () => {
    client = { query: jest.fn().mockResolvedValue({ rows: [] }), release: jest.fn() };
    pool = {
      query: jest.fn().mockResolvedValue({ rows: [] }),
      connect: jest.fn().mockResolvedValue(client),
    };

    const module = await Test.createTestingModule({
      providers: [CatalogService, { provide: PG_POOL, useValue: pool }],
    }).compile();

    service = module.get(CatalogService);
  });

  // --- Lecture ---------------------------------------------------------------

  it('convertit une ligne SQL en document du domaine', async () => {
    pool.query.mockResolvedValue({ rows: [ligneDocument()] });

    const document = await service.document('doc-1');

    expect(document).toMatchObject({
      id: 'doc-1',
      cheminSource: 'contrats/bail.pdf',
      statut: 'analyse',
      niveauMax: 'critique',
      tailleOctets: 2048, // BIGINT rendu en texte par pg, converti ici
    });
  });

  it('rend null pour un document absent', async () => {
    pool.query.mockResolvedValue({ rows: [] });
    expect(await service.document('inconnu')).toBeNull();
  });

  it('accepte une taille nulle sans la convertir en 0', async () => {
    pool.query.mockResolvedValue({ rows: [ligneDocument({ taille_octets: null })] });
    expect((await service.document('doc-1'))?.tailleOctets).toBeNull();
  });

  it('compose les filtres de listage', async () => {
    pool.query
      .mockResolvedValueOnce({ rows: [{ total: '7' }] })
      .mockResolvedValueOnce({ rows: [ligneDocument()] });

    const resultat = await service.lister({ sourceId: 'src-1', statut: 'analyse' });

    expect(resultat.total).toBe(7);
    expect(String(pool.query.mock.calls[1][0])).toContain('source_id = $1');
    expect(String(pool.query.mock.calls[1][0])).toContain('statut = $2');
  });

  // --- Upsert incrémental ----------------------------------------------------

  it("rend null quand l'empreinte est inchangée", async () => {
    // La clause `WHERE ... <> EXCLUDED.empreinte_sha256` ne renvoie aucune
    // ligne : c'est le signal « rien à réanalyser ».
    pool.query.mockResolvedValue({ rows: [] });

    const resultat = await service.upsertDocument({
      sourceId: 'src-1',
      cheminSource: 'a.txt',
      empreinteSha256: 'a'.repeat(64),
    });

    expect(resultat).toBeNull();
  });

  it('réinitialise le statut quand le contenu a changé', async () => {
    pool.query.mockResolvedValue({ rows: [ligneDocument({ statut: 'decouvert' })] });

    const resultat = await service.upsertDocument({
      sourceId: 'src-1',
      cheminSource: 'a.txt',
      empreinteSha256: 'b'.repeat(64),
    });

    expect(resultat?.statut).toBe('decouvert');
    const sql = String(pool.query.mock.calls[0][0]);
    expect(sql).toContain("statut           = 'decouvert'");
    expect(sql).toContain('niveau_max       = NULL');
  });

  it('transtype le statut pour éviter une déduction ambiguë', async () => {
    await service.marquerStatut('doc-1', 'echec', 'moteur indisponible');
    const sql = String(pool.query.mock.calls[0][0]);
    expect(sql).toContain('$2::statut_doc');
  });

  // --- Invariant : aucune valeur en clair ------------------------------------

  const entites: EntiteAnalysee[] = [
    {
      typeEntite: 'IBAN',
      valeur: 'SN91SN0100152000048500000765',
      debut: 10,
      fin: 38,
      page: 1,
      niveau: 'critique',
      score: 0.99,
      methode: 'regle',
    },
    {
      typeEntite: 'NOM_PERSONNE',
      valeur: 'Awa Diouf',
      debut: 50,
      fin: 59,
      page: 1,
      niveau: 'moyen',
      score: 0.94,
      methode: 'ner',
    },
  ];

  it("n'écrit que des empreintes, jamais les valeurs", async () => {
    await service.enregistrerEntites('doc-1', entites, 'critique');

    const insertions = client.query.mock.calls.filter((appel) =>
      String(appel[0]).includes('INSERT INTO entite_detectee'),
    );
    expect(insertions).toHaveLength(2);

    const toutesLesValeurs = JSON.stringify(insertions.map((appel) => appel[1]));
    expect(toutesLesValeurs).not.toContain('SN91SN0100152000048500000765');
    expect(toutesLesValeurs).not.toContain('Awa Diouf');

    for (const insertion of insertions) {
      expect((insertion[1] as string[])[2]).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  it('remplace les entités précédentes dans la même transaction', async () => {
    await service.enregistrerEntites('doc-1', entites, 'critique');

    const sqls = client.query.mock.calls.map((appel) => String(appel[0]));
    expect(sqls[0]).toBe('BEGIN');
    expect(sqls[1]).toContain('DELETE FROM entite_detectee');
    expect(sqls[sqls.length - 1]).toBe('COMMIT');
  });

  it("ne passe pas le document à 'analyse' si l'écriture échoue", async () => {
    client.query.mockImplementation(async (sql: string) => {
      if (String(sql).includes('INSERT INTO entite_detectee')) {
        throw new Error('disque plein');
      }
      return { rows: [] };
    });

    await expect(service.enregistrerEntites('doc-1', entites, 'critique')).rejects.toThrow(
      'disque plein',
    );

    const sqls = client.query.mock.calls.map((appel) => String(appel[0]));
    expect(sqls).toContain('ROLLBACK');
    expect(sqls.some((sql) => sql.includes("statut = 'analyse'"))).toBe(false);
  });

  it('accepte un document sans aucune entité', async () => {
    await service.enregistrerEntites('doc-1', [], null);

    const insertions = client.query.mock.calls.filter((appel) =>
      String(appel[0]).includes('INSERT INTO entite_detectee'),
    );
    expect(insertions).toHaveLength(0);
    expect(client.query).toHaveBeenCalledWith('COMMIT');
  });

  it("les métadonnées d'entités ne comportent ni valeur ni empreinte", async () => {
    pool.query.mockResolvedValue({
      rows: [{ type_entite: 'IBAN', niveau_sensibilite: 'critique', page: 2 }],
    });

    const resultat = await service.entitesDe('doc-1');

    expect(resultat).toEqual([{ typeEntite: 'IBAN', niveau: 'critique', page: 2 }]);
    expect(String(pool.query.mock.calls[0][0])).not.toContain('empreinte_valeur');
  });

  // --- Pseudonymes -----------------------------------------------------------

  it('décode la valeur chiffrée en binaire côté SQL', async () => {
    await service.enregistrerPseudonyme({
      empreinte: 'd'.repeat(64),
      jeton: 'PERS-4F2A',
      valeurChiffreeBase64: 'AAECAw==',
    });

    expect(String(pool.query.mock.calls[0][0])).toContain("decode($3, 'base64')");
  });

  it('ignore un pseudonyme déjà connu', async () => {
    await service.enregistrerPseudonyme({
      empreinte: 'd'.repeat(64),
      jeton: 'PERS-4F2A',
      valeurChiffreeBase64: 'AAECAw==',
    });
    expect(String(pool.query.mock.calls[0][0])).toContain('ON CONFLICT');
  });

  // --- Sources ---------------------------------------------------------------

  it('convertit une ligne source', async () => {
    pool.query.mockResolvedValue({
      rows: [
        {
          id: 'src-1',
          type: 's3',
          libelle: 'Bucket',
          configuration: { bucket: 'documents' },
          frequence_cron: '0 2 * * *',
          dernier_scan: null,
          actif: true,
        },
      ],
    });

    expect(await service.source('src-1')).toMatchObject({
      type: 's3',
      frequenceCron: '0 2 * * *',
      actif: true,
    });
  });

  it('ne liste que les sources actives quand on le demande', async () => {
    pool.query.mockResolvedValue({ rows: [] });
    await service.sources(true);
    expect(String(pool.query.mock.calls[0][0])).toContain('WHERE actif = true');
  });
});
