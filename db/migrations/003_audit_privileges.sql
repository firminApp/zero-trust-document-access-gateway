-- =============================================================================
-- Durcissement du journal d'audit — privilèges
--
-- Les règles `DO INSTEAD NOTHING` de 001 neutralisent UPDATE et DELETE, y
-- compris pour le compte applicatif. Elles ne couvrent PAS deux voies :
--
--   * TRUNCATE — qui n'est pas une suppression ligne à ligne et ne déclenche
--     donc aucune règle ;
--   * la désactivation des règles elle-même
--     (`ALTER TABLE ... DISABLE RULE`), réservée au propriétaire de la table.
--
-- Les deux sont des opérations de propriétaire. La seule parade réelle est
-- donc organisationnelle : **le compte applicatif ne doit pas être
-- propriétaire de `journal_audit`**. Cette migration met en place les droits
-- correspondants ; l'attribution du propriétaire à un rôle distinct relève du
-- déploiement, et reste documentée comme telle plutôt que passée sous silence.
--
-- Ce que le chaînage garantit malgré tout : un journal tronqué ou altéré est
-- DÉTECTABLE. `verifyChain()` signale la rupture. On ne prétend pas empêcher
-- un administrateur de base de détruire la table — on garantit qu'il ne peut
-- pas le faire sans que cela se voie.
-- =============================================================================

-- Personne d'autre que le propriétaire ne touche au journal.
REVOKE ALL ON journal_audit FROM PUBLIC;

DO $$
BEGIN
  -- Rôle applicatif dédié à la passerelle, si le déploiement l'a créé.
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ztg_app') THEN
    GRANT SELECT, INSERT ON journal_audit TO ztg_app;
    GRANT USAGE, SELECT ON SEQUENCE journal_audit_id_seq TO ztg_app;
    -- Ni UPDATE, ni DELETE, ni TRUNCATE : le compte qui écrit le journal ne
    -- doit pas pouvoir le réécrire.
    REVOKE UPDATE, DELETE, TRUNCATE ON journal_audit FROM ztg_app;
  END IF;
END $$;

COMMENT ON TABLE journal_audit IS
  'Journal append-only chaîné par empreinte SHA-256. UPDATE et DELETE sont '
  'neutralisés par règle. TRUNCATE et DISABLE RULE restent des opérations de '
  'propriétaire : en production, le compte applicatif ne doit pas être '
  'propriétaire de cette table. Toute altération reste détectable par '
  'GET /api/v1/audit/verification.';
