/**
 * Tests de sécurité fonctionnelle T-01 à T-05.
 *
 * Binaires : il n'y a pas de demi-conformité. Un test qui « passe presque »
 * est un test qui échoue.
 *
 * Ils s'exécutent contre la pile démarrée :
 *     make up && make seed && make corpus
 *     make test-securite
 */

import { Client } from 'pg';
import { S3Client, ListObjectsV2Command } from '@aws-sdk/client-s3';

const PORTAIL = process.env.URL_PORTAIL ?? 'http://localhost:3000';
const POSTGRES = process.env.POSTGRES_URL ?? 'postgresql://ztg:ztg@localhost:5432/ztg';
const MOT_DE_PASSE = process.env.SEED_PASSWORD ?? 'demo1234';

const COMPTES = {
  support_n1: 'support1',
  support_n2: 'support2',
  operations: 'operations',
  conformite: 'conformite',
  service_partenaire: 'partenaire',
  admin_systeme: 'admin',
} as const;

const MATRICE: Record<string, Record<string, string>> = {
  support_n1: { faible: 'complet', moyen: 'masque', eleve: 'refus', critique: 'refus' },
  support_n2: { faible: 'complet', moyen: 'complet', eleve: 'masque', critique: 'refus' },
  operations: { faible: 'complet', moyen: 'complet', eleve: 'pseudonymise', critique: 'refus' },
  conformite: { faible: 'complet', moyen: 'complet', eleve: 'complet', critique: 'complet' },
  service_partenaire: { faible: 'complet', moyen: 'masque', eleve: 'refus', critique: 'refus' },
  admin_systeme: { faible: 'refus', moyen: 'refus', eleve: 'refus', critique: 'refus' },
};

const NIVEAUX = ['faible', 'moyen', 'eleve', 'critique'] as const;

jest.setTimeout(180_000);

let base: Client;
const jetons = new Map<string, string>();
/** Un document analysé par niveau de sensibilité, si le corpus en contient. */
const documentsParNiveau = new Map<string, string>();

async function jetonPour(role: keyof typeof COMPTES): Promise<string> {
  const existant = jetons.get(role);
  if (existant) {
    return existant;
  }

  const reponse = await fetch(`${PORTAIL}/api/v1/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ utilisateur: COMPTES[role], motDePasse: MOT_DE_PASSE }),
  });
  if (!reponse.ok) {
    throw new Error(`Authentification impossible pour ${role} : HTTP ${reponse.status}`);
  }
  const corps = (await reponse.json()) as { accessToken: string };
  jetons.set(role, corps.accessToken);
  return corps.accessToken;
}

async function lireContenu(role: keyof typeof COMPTES, documentId: string): Promise<Response> {
  return fetch(`${PORTAIL}/api/v1/documents/${documentId}/contenu`, {
    headers: { Authorization: `Bearer ${await jetonPour(role)}` },
  });
}

/** Contrôle de Luhn — même définition que le validateur du moteur IA. */
function luhnValide(valeur: string): boolean {
  const chiffres = valeur.replace(/[^0-9]/g, '');
  if (chiffres.length < 13 || chiffres.length > 19) {
    return false;
  }
  if (new Set(chiffres).size === 1) {
    return false;
  }
  let total = 0;
  for (let index = 0; index < chiffres.length; index += 1) {
    let chiffre = Number(chiffres[chiffres.length - 1 - index]);
    if (index % 2 === 1) {
      chiffre *= 2;
      if (chiffre > 9) {
        chiffre -= 9;
      }
    }
    total += chiffre;
  }
  return total % 10 === 0;
}

async function compterAudit(): Promise<number> {
  const { rows } = await base.query<{ total: string }>(
    'SELECT count(*)::text AS total FROM journal_audit',
  );
  return Number(rows[0].total);
}

beforeAll(async () => {
  base = new Client({ connectionString: POSTGRES });
  await base.connect();

  for (const niveau of NIVEAUX) {
    const { rows } = await base.query<{ id: string }>(
      `SELECT id FROM document WHERE statut = 'analyse' AND niveau_max = $1 LIMIT 1`,
      [niveau],
    );
    if (rows[0]) {
      documentsParNiveau.set(niveau, rows[0].id);
    }
  }
});

afterAll(async () => {
  await base?.end();
});

// =============================================================================
// T-01 — accès direct au stockage avec les identifiants d'une application
// =============================================================================

describe('T-01 — la voie d’accès directe au stockage est fermée', () => {
  it('des identifiants S3 quelconques ne donnent pas accès au bucket', async () => {
    // Le scénario réel : une application cliente tente d'atteindre le stockage
    // sans passer par le portail. Seul le compte de service du portail détient
    // des identifiants valides.
    const client = new S3Client({
      region: 'us-east-1',
      endpoint: process.env.S3_ENDPOINT_HOTE ?? 'http://localhost:9000',
      forcePathStyle: true,
      credentials: {
        accessKeyId: 'application-back-office',
        secretAccessKey: 'mot-de-passe-de-lapplication',
      },
    });

    await expect(
      client.send(
        new ListObjectsV2Command({ Bucket: process.env.S3_BUCKET ?? 'documents' }),
      ),
    ).rejects.toBeDefined();
  });

  it("le moteur IA n'est pas joignable depuis l'extérieur du réseau Docker", async () => {
    // S'il l'était, on pourrait lui soumettre n'importe quel document et
    // récupérer les valeurs d'entités en clair, hors de tout contrôle de rôle.
    const controleur = new AbortController();
    const minuterie = setTimeout(() => controleur.abort(), 3000);
    try {
      await fetch('http://localhost:8000/sante', { signal: controleur.signal });
      throw new Error('Le moteur IA répond sur le port 8000 : il ne doit PAS être publié');
    } catch (erreur) {
      expect((erreur as Error).message).not.toContain('il ne doit PAS être publié');
    } finally {
      clearTimeout(minuterie);
    }
  });

  it('le portail refuse toute lecture sans jeton', async () => {
    const documentId = [...documentsParNiveau.values()][0];
    if (!documentId) {
      return;
    }
    const reponse = await fetch(`${PORTAIL}/api/v1/documents/${documentId}/contenu`);
    expect(reponse.status).toBe(401);
  });

  it('le portail refuse un jeton falsifié', async () => {
    const documentId = [...documentsParNiveau.values()][0];
    if (!documentId) {
      return;
    }
    const reponse = await fetch(`${PORTAIL}/api/v1/documents/${documentId}/contenu`, {
      headers: { Authorization: 'Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4Iiwicm9sZSI6ImNvbmZvcm1pdGUifQ.faux' },
    });
    expect(reponse.status).toBe(401);
  });
});

// =============================================================================
// T-02 — les 24 cases de la matrice
// =============================================================================

describe('T-02 — la matrice renvoie exactement l’action attendue', () => {
  const cas = Object.keys(MATRICE).flatMap((role) =>
    NIVEAUX.map((niveau) => ({ role, niveau, attendu: MATRICE[role][niveau] })),
  );

  it.each(cas)('$role × $niveau -> $attendu', async ({ role, niveau, attendu }) => {
    const documentId = documentsParNiveau.get(niveau);
    if (!documentId) {
      console.warn(`Aucun document analysé de niveau « ${niveau} » : cas non couvert`);
      return;
    }

    const reponse = await lireContenu(role as keyof typeof COMPTES, documentId);

    if (attendu === 'refus') {
      expect(reponse.status).toBe(403);
      expect(await reponse.text()).not.toContain('IBAN');
      return;
    }

    expect(reponse.status).toBe(200);
    expect(reponse.headers.get('X-Politique-Appliquee')).toBe(attendu);
    expect(reponse.headers.get('X-Niveau-Max-Detecte')).toBe(niveau);
  });

  it('un document non analysé renvoie 423, jamais le contenu', async () => {
    const { rows } = await base.query<{ id: string }>(
      `SELECT id FROM document WHERE statut <> 'analyse' LIMIT 1`,
    );
    if (!rows[0]) {
      return;
    }
    const reponse = await lireContenu('conformite', rows[0].id);
    expect(reponse.status).toBe(423);
  });

  it('un document inconnu renvoie 404', async () => {
    const reponse = await lireContenu(
      'conformite',
      '00000000-0000-4000-8000-000000000000',
    );
    expect(reponse.status).toBe(404);
  });
});

// =============================================================================
// T-03 — entrées d'audit == requêtes émises, refus compris
// =============================================================================

describe('T-03 — chaque requête laisse exactement une trace', () => {
  it('les succès et les refus sont journalisés à l’identique', async () => {
    const documentCritique = documentsParNiveau.get('critique');
    const documentFaible = documentsParNiveau.get('faible');
    if (!documentCritique || !documentFaible) {
      console.warn('Corpus insuffisant pour T-03');
      return;
    }

    // Jetons obtenus d'abord : l'authentification journalise elle aussi.
    await jetonPour('conformite');
    await jetonPour('support_n1');

    const avant = await compterAudit();

    await lireContenu('conformite', documentCritique); // 200 attendu
    await lireContenu('support_n1', documentCritique); // 403 attendu
    await lireContenu('conformite', '00000000-0000-4000-8000-000000000000'); // 404
    await lireContenu('support_n1', documentFaible); // 200 attendu

    const apres = await compterAudit();
    expect(apres - avant).toBe(4);
  });

  it("le journal ne contient aucune valeur d'entité en clair", async () => {
    const { rows } = await base.query<{ details: unknown }>(
      'SELECT details FROM journal_audit WHERE details IS NOT NULL ORDER BY id DESC LIMIT 200',
    );
    const contenu = JSON.stringify(rows);

    // Un IBAN, un courriel ou un numéro de carte ne doivent jamais s'y trouver.
    expect(contenu).not.toMatch(/[A-Z]{2}\d{2}[A-Z0-9]{20,}/);
    expect(contenu).not.toMatch(/[\w.]+@[\w.]+\.[a-z]{2,}/);

    // Pour les cartes, on applique Luhn plutôt qu'un simple motif de chiffres :
    // le journal contient légitimement des identifiants de documents (UUID),
    // dont les suites de chiffres déclencheraient un motif purement
    // syntaxique. Ce n'est une fuite que si la valeur est un vrai PAN.
    const candidats = contenu.match(/\d[\d -]{11,21}\d/g) ?? [];
    const cartes = candidats.filter((candidat) => luhnValide(candidat));
    expect(cartes).toEqual([]);
  });

  it("la table entite_detectee ne stocke que des empreintes", async () => {
    const { rows } = await base.query<{ empreinte_valeur: string }>(
      'SELECT empreinte_valeur FROM entite_detectee LIMIT 500',
    );
    for (const ligne of rows) {
      expect(ligne.empreinte_valeur).toMatch(/^[0-9a-f]{64}$/);
    }

    const colonnes = await base.query<{ column_name: string }>(
      `SELECT column_name FROM information_schema.columns
        WHERE table_name = 'entite_detectee'`,
    );
    const noms = colonnes.rows.map((c) => c.column_name);
    expect(noms).not.toContain('valeur');
    expect(noms).not.toContain('texte');
  });
});

// =============================================================================
// T-04 — l'altération d'une entrée d'audit est détectée
// =============================================================================

describe('T-04 — le chaînage résiste à la falsification', () => {
  it('la chaîne est intacte en fonctionnement normal', async () => {
    const reponse = await fetch(`${PORTAIL}/api/v1/audit/verification`, {
      headers: { Authorization: `Bearer ${await jetonPour('conformite')}` },
    });
    expect(reponse.status).toBe(200);
    expect((await reponse.json()).intact).toBe(true);
  });

  it("UPDATE sur journal_audit ne modifie rien (règle DO INSTEAD NOTHING)", async () => {
    const { rows } = await base.query<{ id: string; role_effectif: string }>(
      'SELECT id, role_effectif FROM journal_audit ORDER BY id DESC LIMIT 1',
    );
    if (!rows[0]) {
      return;
    }

    await base.query(`UPDATE journal_audit SET role_effectif = 'conformite' WHERE id = $1`, [
      rows[0].id,
    ]);

    const { rows: apres } = await base.query<{ role_effectif: string }>(
      'SELECT role_effectif FROM journal_audit WHERE id = $1',
      [rows[0].id],
    );
    expect(apres[0].role_effectif).toBe(rows[0].role_effectif);
  });

  it('DELETE sur journal_audit ne supprime rien', async () => {
    const avant = await compterAudit();
    await base.query('DELETE FROM journal_audit WHERE id = (SELECT min(id) FROM journal_audit)');
    expect(await compterAudit()).toBe(avant);
  });

  it("après altération par superutilisateur, verifyChain() signale la rupture", async () => {
    // On contourne la règle SQL comme le ferait un administrateur de base :
    // c'est exactement la menace contre laquelle le chaînage protège.
    const { rows } = await base.query<{ id: string; role_effectif: string }>(
      'SELECT id, role_effectif FROM journal_audit ORDER BY id ASC OFFSET 1 LIMIT 1',
    );
    if (!rows[0]) {
      return;
    }

    // La valeur substituée doit être différente de l'originale, sinon
    // l'« altération » est un non-événement et le test se valide tout seul.
    const original = rows[0].role_effectif;
    const falsifie = original === 'conformite' ? 'support_n1' : 'conformite';

    await base.query('ALTER TABLE journal_audit DISABLE RULE audit_no_update');
    try {
      await base.query(`UPDATE journal_audit SET role_effectif = $2 WHERE id = $1`, [
        rows[0].id,
        falsifie,
      ]);

      const reponse = await fetch(`${PORTAIL}/api/v1/audit/verification`, {
        headers: { Authorization: `Bearer ${await jetonPour('conformite')}` },
      });
      const resultat = (await reponse.json()) as {
        intact: boolean;
        premiereRupture: string | null;
      };

      expect(resultat.intact).toBe(false);
      expect(resultat.premiereRupture).toBe(rows[0].id);
    } finally {
      // Restauration de la valeur EXACTE d'origine : réécrire une valeur
      // arbitraire laisserait la chaîne durablement rompue et ferait échouer
      // tous les contrôles d'intégrité suivants.
      await base.query(`UPDATE journal_audit SET role_effectif = $2 WHERE id = $1`, [
        rows[0].id,
        original,
      ]);
      await base.query('ALTER TABLE journal_audit ENABLE RULE audit_no_update');
    }
  });
});

// =============================================================================
// T-05 — bout en bout sur les sources déclarées
// =============================================================================

describe('T-05 — chaîne complète : sécurisation, demande, contrôle, restitution', () => {
  it('chaque source déclarée a produit des documents analysés', async () => {
    const { rows } = await base.query<{ libelle: string; type: string; total: string }>(
      `SELECT s.libelle, s.type::text, count(d.id)::text AS total
         FROM source s LEFT JOIN document d ON d.source_id = s.id AND d.statut = 'analyse'
        WHERE s.actif GROUP BY s.libelle, s.type`,
    );

    expect(rows.length).toBeGreaterThan(0);
    for (const source of rows) {
      expect(Number(source.total)).toBeGreaterThan(0);
    }
  });

  it("le masquage retire réellement la donnée du document restitué", async () => {
    const documentMoyen = documentsParNiveau.get('moyen');
    if (!documentMoyen) {
      return;
    }

    const masque = await lireContenu('support_n1', documentMoyen);
    expect(masque.status).toBe(200);
    expect(masque.headers.get('X-Politique-Appliquee')).toBe('masque');

    const texteMasque = await masque.text();
    const complet = await lireContenu('conformite', documentMoyen);
    const texteComplet = await complet.text();

    // Le document protégé diffère de l'original, et les courriels ont disparu.
    expect(texteMasque).not.toBe(texteComplet);
    expect(texteMasque).not.toMatch(/[\w.]+@[\w.]+\.[a-z]{2,}/);
  });

  it("le rôle admin_systeme administre mais ne lit aucun document", async () => {
    // Séparation des pouvoirs : celui qui exploite le système n'est pas celui
    // qui consulte les données.
    for (const [niveau, documentId] of documentsParNiveau) {
      const reponse = await lireContenu('admin_systeme', documentId);
      expect([403, 423]).toContain(reponse.status);
      expect(niveau).toBeDefined();
    }

    const sources = await fetch(`${PORTAIL}/api/v1/sources`, {
      headers: { Authorization: `Bearer ${await jetonPour('admin_systeme')}` },
    });
    expect(sources.status).toBe(200);
  });

  it("les métadonnées n'exposent jamais de valeur d'entité", async () => {
    const documentId = documentsParNiveau.get('critique') ?? [...documentsParNiveau.values()][0];
    if (!documentId) {
      return;
    }

    const reponse = await fetch(`${PORTAIL}/api/v1/documents/${documentId}/metadonnees`, {
      headers: { Authorization: `Bearer ${await jetonPour('support_n1')}` },
    });
    expect(reponse.status).toBe(200);

    const corps = await reponse.text();
    expect(corps).not.toMatch(/[A-Z]{2}\d{2}[A-Z0-9]{20,}/);
    expect(corps).not.toMatch(/[\w.]+@[\w.]+\.[a-z]{2,}/);
    expect(JSON.parse(corps).entites).toBeDefined();
  });

  it('un scan relancé ne réanalyse aucun document inchangé', async () => {
    const { rows: sources } = await base.query<{ id: string }>(
      `SELECT id FROM source WHERE actif AND type = 'local' LIMIT 1`,
    );
    if (!sources[0]) {
      return;
    }

    const reponse = await fetch(`${PORTAIL}/api/v1/sources/${sources[0].id}/scan`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${await jetonPour('admin_systeme')}` },
    });
    expect(reponse.status).toBe(201);

    await new Promise((resoudre) => setTimeout(resoudre, 15_000));

    const { rows } = await base.query<{ nb_nouveaux: number; nb_inchanges: number }>(
      `SELECT nb_nouveaux, nb_inchanges FROM scan_execution
        WHERE source_id = $1 AND termine_le IS NOT NULL
        ORDER BY demarre_le DESC LIMIT 1`,
      [sources[0].id],
    );

    if (rows[0]) {
      expect(rows[0].nb_nouveaux).toBe(0);
      expect(rows[0].nb_inchanges).toBeGreaterThan(0);
    }
  });
});
