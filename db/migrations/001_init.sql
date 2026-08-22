-- =============================================================================
-- Zero-Trust Document Access Gateway — schéma initial
-- PostgreSQL 16
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  CREATE TYPE type_source     AS ENUM ('s3','gdrive','local');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE niveau_sens     AS ENUM ('faible','moyen','eleve','critique');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE action_acces    AS ENUM ('complet','masque','pseudonymise','refus');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE statut_doc      AS ENUM ('decouvert','en_analyse','analyse','echec');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE methode_detect  AS ENUM ('regle','ner','fusion');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- -----------------------------------------------------------------------------
-- Sources de stockage
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type            type_source NOT NULL,
  libelle         TEXT NOT NULL,
  configuration   JSONB NOT NULL,
  frequence_cron  TEXT NOT NULL DEFAULT '0 2 * * *',
  dernier_scan    TIMESTAMPTZ,
  actif           BOOLEAN NOT NULL DEFAULT true
);

-- -----------------------------------------------------------------------------
-- Catalogue de documents
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id        UUID NOT NULL REFERENCES source(id),
  chemin_source    TEXT NOT NULL,
  empreinte_sha256 CHAR(64) NOT NULL,
  type_mime        TEXT,
  taille_octets    BIGINT,
  statut           statut_doc NOT NULL DEFAULT 'decouvert',
  niveau_max       niveau_sens,
  date_decouverte  TIMESTAMPTZ NOT NULL DEFAULT now(),
  date_analyse     TIMESTAMPTZ,
  tentatives       SMALLINT NOT NULL DEFAULT 0,
  motif_echec      TEXT,
  UNIQUE (source_id, chemin_source)
);
CREATE INDEX IF NOT EXISTS document_statut_idx    ON document (statut);
CREATE INDEX IF NOT EXISTS document_src_hash_idx  ON document (source_id, empreinte_sha256);

-- -----------------------------------------------------------------------------
-- Entités détectées.
-- INVARIANT : jamais la valeur en clair. Uniquement une empreinte + la position.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entite_detectee (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id        UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  type_entite        TEXT NOT NULL,
  empreinte_valeur   CHAR(64) NOT NULL,
  position_debut     INTEGER NOT NULL,
  position_fin       INTEGER NOT NULL,
  page               SMALLINT,
  niveau_sensibilite niveau_sens NOT NULL,
  score_confiance    REAL,
  methode            methode_detect NOT NULL
);
CREATE INDEX IF NOT EXISTS entite_document_idx ON entite_detectee (document_id);
CREATE INDEX IF NOT EXISTS entite_type_idx     ON entite_detectee (type_entite);

-- -----------------------------------------------------------------------------
-- RBAC
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS role (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code              TEXT UNIQUE NOT NULL,
  libelle           TEXT NOT NULL,
  action_par_defaut action_acces NOT NULL DEFAULT 'refus'
);

CREATE TABLE IF NOT EXISTS politique_acces (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  role_id            UUID NOT NULL REFERENCES role(id),
  niveau_sensibilite niveau_sens NOT NULL,
  action             action_acces NOT NULL,
  UNIQUE (role_id, niveau_sensibilite)
);

-- Comptes applicatifs de démonstration (le mot de passe est un hash bcrypt).
CREATE TABLE IF NOT EXISTS utilisateur (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  identifiant     TEXT UNIQUE NOT NULL,
  mot_de_passe    TEXT NOT NULL,
  role_code       TEXT NOT NULL REFERENCES role(code),
  actif           BOOLEAN NOT NULL DEFAULT true,
  cree_le         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Journal d'audit — append-only, chaîné cryptographiquement.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journal_audit (
  id                   BIGSERIAL PRIMARY KEY,
  horodatage           TIMESTAMPTZ NOT NULL DEFAULT now(),
  utilisateur_id       TEXT NOT NULL,
  role_effectif        TEXT NOT NULL,
  document_id          UUID,
  action               TEXT NOT NULL,
  politique_appliquee  action_acces,
  niveau_en_cause      niveau_sens,
  adresse_ip           INET,
  details              JSONB,
  empreinte_precedente CHAR(64),
  empreinte            CHAR(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_doc_idx  ON journal_audit (document_id, horodatage DESC);
CREATE INDEX IF NOT EXISTS audit_user_idx ON journal_audit (utilisateur_id, horodatage DESC);

-- Interdiction structurelle de la modification : les règles transforment
-- UPDATE et DELETE en opérations sans effet, y compris pour le compte applicatif.
DROP RULE IF EXISTS audit_no_update ON journal_audit;
DROP RULE IF EXISTS audit_no_delete ON journal_audit;
CREATE RULE audit_no_update AS ON UPDATE TO journal_audit DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO journal_audit DO INSTEAD NOTHING;

-- -----------------------------------------------------------------------------
-- Table de correspondance des pseudonymes (valeur chiffrée, clé hors base)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pseudonyme (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  empreinte_valeur CHAR(64) UNIQUE NOT NULL,
  jeton            TEXT UNIQUE NOT NULL,
  valeur_chiffree  BYTEA NOT NULL,
  cree_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Historique des scans (alimente le tableau de bord M7)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scan_execution (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id       UUID NOT NULL REFERENCES source(id),
  demarre_le      TIMESTAMPTZ NOT NULL DEFAULT now(),
  termine_le      TIMESTAMPTZ,
  nb_listes       INTEGER NOT NULL DEFAULT 0,
  nb_nouveaux     INTEGER NOT NULL DEFAULT 0,
  nb_inchanges    INTEGER NOT NULL DEFAULT 0,
  nb_echecs       INTEGER NOT NULL DEFAULT 0,
  declencheur     TEXT NOT NULL DEFAULT 'cron'
);
CREATE INDEX IF NOT EXISTS scan_source_idx ON scan_execution (source_id, demarre_le DESC);
