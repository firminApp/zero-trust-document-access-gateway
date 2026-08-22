/**
 * Migrations versionnées + amorçage de démonstration (`make seed`).
 *
 * Idempotent : relancer la commande ne duplique rien. Les fichiers SQL déjà
 * appliqués sont enregistrés dans `schema_migrations`.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import * as bcrypt from 'bcryptjs';
import { Pool } from 'pg';

const REPERTOIRE_MIGRATIONS =
  process.env.MIGRATIONS_DIR ?? resolve(__dirname, '../../..', 'db/migrations');

/** Comptes de démonstration — un par rôle, pour dérouler la matrice à la main. */
const COMPTES_DEMO: Array<{ identifiant: string; role: string }> = [
  { identifiant: 'support1', role: 'support_n1' },
  { identifiant: 'support2', role: 'support_n2' },
  { identifiant: 'operations', role: 'operations' },
  { identifiant: 'conformite', role: 'conformite' },
  { identifiant: 'partenaire', role: 'service_partenaire' },
  { identifiant: 'admin', role: 'admin_systeme' },
];

async function appliquerMigrations(pool: Pool): Promise<void> {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      fichier    TEXT PRIMARY KEY,
      applique_le TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `);

  const fichiers = readdirSync(REPERTOIRE_MIGRATIONS)
    .filter((f) => f.endsWith('.sql'))
    .sort();

  for (const fichier of fichiers) {
    const { rowCount } = await pool.query(
      'SELECT 1 FROM schema_migrations WHERE fichier = $1',
      [fichier],
    );
    if (rowCount) {
      console.log(`  = ${fichier} (déjà appliquée)`);
      continue;
    }

    const sql = readFileSync(join(REPERTOIRE_MIGRATIONS, fichier), 'utf8');
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(sql);
      await client.query('INSERT INTO schema_migrations (fichier) VALUES ($1)', [fichier]);
      await client.query('COMMIT');
      console.log(`  + ${fichier}`);
    } catch (erreur) {
      await client.query('ROLLBACK');
      throw new Error(`Migration ${fichier} en échec : ${(erreur as Error).message}`);
    } finally {
      client.release();
    }
  }
}

async function amorcerUtilisateurs(pool: Pool): Promise<void> {
  const motDePasse = process.env.SEED_PASSWORD ?? 'demo1234';
  const empreinte = await bcrypt.hash(motDePasse, 10);

  for (const compte of COMPTES_DEMO) {
    await pool.query(
      `INSERT INTO utilisateur (identifiant, mot_de_passe, role_code)
       VALUES ($1, $2, $3)
       ON CONFLICT (identifiant) DO UPDATE
         SET mot_de_passe = EXCLUDED.mot_de_passe, role_code = EXCLUDED.role_code`,
      [compte.identifiant, empreinte, compte.role],
    );
  }
  console.log(`  ${COMPTES_DEMO.length} comptes de démonstration (mot de passe : ${motDePasse})`);
}

async function amorcerSources(pool: Pool): Promise<void> {
  const sources: Array<{
    type: string;
    libelle: string;
    configuration: Record<string, unknown>;
  }> = [
    {
      type: 'local',
      libelle: 'Disque local — corpus de démonstration',
      configuration: { chemin: process.env.LOCAL_ROOT ?? '/data/local' },
    },
  ];

  if (process.env.S3_ACCESS_KEY) {
    sources.push({
      type: 's3',
      libelle: 'Bucket S3 (MinIO) — pièces justificatives',
      configuration: {
        bucket: process.env.S3_BUCKET ?? 'documents',
        prefixe: '',
        endpoint: process.env.S3_ENDPOINT ?? 'http://minio:9000',
      },
    });
  }

  if (process.env.GDRIVE_SERVICE_ACCOUNT_JSON) {
    sources.push({
      type: 'gdrive',
      libelle: 'Google Drive — dossiers partagés',
      configuration: { folderId: process.env.GDRIVE_FOLDER_ID ?? 'root' },
    });
  }

  for (const source of sources) {
    await pool.query(
      `INSERT INTO source (type, libelle, configuration, frequence_cron)
       SELECT $1::type_source, $2, $3::jsonb, $4
       WHERE NOT EXISTS (SELECT 1 FROM source WHERE libelle = $2)`,
      [source.type, source.libelle, JSON.stringify(source.configuration), '0 2 * * *'],
    );
  }
  console.log(`  ${sources.length} source(s) de démonstration`);
}

async function principal(): Promise<void> {
  const pool = new Pool({
    connectionString: process.env.POSTGRES_URL ?? 'postgresql://ztg:ztg@localhost:5432/ztg',
  });

  try {
    console.log('Migrations :');
    await appliquerMigrations(pool);
    console.log('Amorçage :');
    await amorcerUtilisateurs(pool);
    await amorcerSources(pool);
    console.log('Terminé.');
  } finally {
    await pool.end();
  }
}

if (require.main === module) {
  principal().catch((erreur) => {
    console.error(erreur);
    process.exit(1);
  });
}

export { appliquerMigrations, amorcerUtilisateurs, amorcerSources };
