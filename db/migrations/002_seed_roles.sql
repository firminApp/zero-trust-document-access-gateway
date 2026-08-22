-- =============================================================================
-- Rôles et matrice de politique d'accès (M1)
--
-- Rôle × niveau de sensibilité -> action. Toute case absente vaut « refus » :
-- PolicyService ne lit jamais un défaut permissif.
--
-- Note : admin_systeme administre la passerelle mais ne lit AUCUN document.
-- La séparation des pouvoirs est le point : celui qui exploite le système
-- n'est pas celui qui consulte les données.
-- =============================================================================

INSERT INTO role (code, libelle, action_par_defaut) VALUES
  ('support_n1',         'Support niveau 1',            'refus'),
  ('support_n2',         'Support niveau 2',            'refus'),
  ('operations',         'Opérations',                  'refus'),
  ('conformite',         'Conformité / DPO',            'refus'),
  ('service_partenaire', 'Service partenaire externe',  'refus'),
  ('admin_systeme',      'Administrateur système',      'refus')
ON CONFLICT (code) DO NOTHING;

INSERT INTO politique_acces (role_id, niveau_sensibilite, action)
SELECT r.id, m.niveau::niveau_sens, m.action::action_acces
FROM role r
JOIN (VALUES
  ('support_n1',         'faible',   'complet'),
  ('support_n1',         'moyen',    'masque'),
  ('support_n1',         'eleve',    'refus'),
  ('support_n1',         'critique', 'refus'),

  ('support_n2',         'faible',   'complet'),
  ('support_n2',         'moyen',    'complet'),
  ('support_n2',         'eleve',    'masque'),
  ('support_n2',         'critique', 'refus'),

  ('operations',         'faible',   'complet'),
  ('operations',         'moyen',    'complet'),
  ('operations',         'eleve',    'pseudonymise'),
  ('operations',         'critique', 'refus'),

  ('conformite',         'faible',   'complet'),
  ('conformite',         'moyen',    'complet'),
  ('conformite',         'eleve',    'complet'),
  ('conformite',         'critique', 'complet'),

  ('service_partenaire', 'faible',   'complet'),
  ('service_partenaire', 'moyen',    'masque'),
  ('service_partenaire', 'eleve',    'refus'),
  ('service_partenaire', 'critique', 'refus'),

  ('admin_systeme',      'faible',   'refus'),
  ('admin_systeme',      'moyen',    'refus'),
  ('admin_systeme',      'eleve',    'refus'),
  ('admin_systeme',      'critique', 'refus')
) AS m(role_code, niveau, action) ON m.role_code = r.code
ON CONFLICT (role_id, niveau_sensibilite) DO UPDATE SET action = EXCLUDED.action;
