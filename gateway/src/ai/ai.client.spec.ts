import { AiClient, MoteurIaIndisponibleError } from './ai.client';

/**
 * Client du moteur IA.
 *
 * Point vérifié en priorité : toute défaillance du moteur remonte comme
 * `MoteurIaIndisponibleError`, jamais comme un résultat vide. Un échec traduit
 * en « aucune entité détectée » ferait passer un document sensible pour
 * inoffensif — l'inverse exact du refus par défaut.
 */
describe('AiClient', () => {
  let client: AiClient;
  let fetchSimule: jest.Mock;

  beforeEach(() => {
    process.env.AI_ENGINE_URL = 'http://moteur-ia:8000';
    client = new AiClient();
    fetchSimule = jest.fn();
    global.fetch = fetchSimule as unknown as typeof fetch;
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  function reponseOk(corps: unknown): Response {
    return {
      ok: true,
      status: 200,
      json: async () => corps,
      text: async () => JSON.stringify(corps),
    } as Response;
  }

  it('encode le contenu en base64 et rend les entités', async () => {
    fetchSimule.mockResolvedValue(
      reponseOk({
        texteExtrait: true,
        methodeExtraction: 'plain',
        cerEstime: null,
        entites: [{ typeEntite: 'EMAIL', valeur: 'a@b.sn', debut: 0, fin: 6 }],
        niveauMax: 'moyen',
        nbCaracteres: 42,
        nbPages: 1,
      }),
    );

    const resultat = await client.analyser({
      documentId: 'doc-1',
      typeMime: 'text/plain',
      contenu: Buffer.from('contenu'),
    });

    expect(resultat.niveauMax).toBe('moyen');
    const corps = JSON.parse(fetchSimule.mock.calls[0][1].body as string);
    expect(corps.contenuBase64).toBe(Buffer.from('contenu').toString('base64'));
    expect(fetchSimule.mock.calls[0][0]).toBe('http://moteur-ia:8000/analyser');
  });

  it('décode le contenu protégé et remonte les correspondances', async () => {
    const protege = Buffer.from('j••••••@••••');
    fetchSimule.mockResolvedValue(
      reponseOk({
        contenuBase64: protege.toString('base64'),
        nbEntitesProtegees: 1,
        typeMimeSortie: 'text/plain',
        correspondances: [
          { empreinte: 'a'.repeat(64), jeton: 'PERS-1234', valeurChiffreeBase64: 'AAEC' },
        ],
      }),
    );

    const resultat = await client.proteger({
      documentId: 'doc-1',
      typeMime: 'text/plain',
      contenu: Buffer.from('jean@mail.com'),
      action: 'masque',
      niveauSeuil: 'moyen',
    });

    expect(resultat.contenu.toString()).toBe('j••••••@••••');
    expect(resultat.correspondances).toHaveLength(1);
  });

  it('tolère une réponse de protection sans correspondances', async () => {
    fetchSimule.mockResolvedValue(
      reponseOk({
        contenuBase64: Buffer.from('x').toString('base64'),
        nbEntitesProtegees: 0,
        typeMimeSortie: 'text/plain',
      }),
    );

    const resultat = await client.proteger({
      documentId: 'doc-1',
      typeMime: 'text/plain',
      contenu: Buffer.from('x'),
      action: 'masque',
      niveauSeuil: 'moyen',
    });

    expect(resultat.correspondances).toEqual([]);
  });

  it('transforme une erreur HTTP en MoteurIaIndisponibleError', async () => {
    fetchSimule.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => 'boum',
      json: async () => ({}),
    } as Response);

    await expect(
      client.analyser({ documentId: 'd', typeMime: null, contenu: Buffer.from('x') }),
    ).rejects.toBeInstanceOf(MoteurIaIndisponibleError);
  });

  it('transforme une panne réseau en MoteurIaIndisponibleError', async () => {
    fetchSimule.mockRejectedValue(new Error('ECONNREFUSED'));

    await expect(
      client.analyser({ documentId: 'd', typeMime: null, contenu: Buffer.from('x') }),
    ).rejects.toBeInstanceOf(MoteurIaIndisponibleError);
  });

  it('interroge la santé du moteur en GET, sans corps', async () => {
    fetchSimule.mockResolvedValue(
      reponseOk({ statut: 'ok', modeleNer: 'camembert', versionTesseract: '5.5.0' }),
    );

    expect((await client.sante()).statut).toBe('ok');
    expect(fetchSimule.mock.calls[0][1].method).toBe('GET');
    expect(fetchSimule.mock.calls[0][1].body).toBeUndefined();
  });

  it('arme un signal d’abandon sur chaque appel', async () => {
    fetchSimule.mockResolvedValue(reponseOk({ statut: 'ok' }));
    await client.sante();
    expect(fetchSimule.mock.calls[0][1].signal).toBeDefined();
  });
});
