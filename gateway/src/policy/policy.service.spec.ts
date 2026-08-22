import { Test } from '@nestjs/testing';
import { ActionAcces, NIVEAUX, NiveauSens } from '../common/types';
import { PolicyRepository } from './policy.repository';
import { NiveauInconnuError, PolicyService } from './policy.service';

/**
 * T-02 — les 24 cases de la matrice (6 rôles × 4 niveaux).
 *
 * Le test est exhaustif par construction : la table de référence ci-dessous
 * est déroulée case par case, et un test supplémentaire vérifie qu'aucune case
 * n'a été oubliée. Tester la matrice partiellement laisserait une faille
 * silencieuse (piège n°8).
 */

const MATRICE_ATTENDUE: Record<string, Record<NiveauSens, ActionAcces>> = {
  support_n1: { faible: 'complet', moyen: 'masque', eleve: 'refus', critique: 'refus' },
  support_n2: { faible: 'complet', moyen: 'complet', eleve: 'masque', critique: 'refus' },
  operations: { faible: 'complet', moyen: 'complet', eleve: 'pseudonymise', critique: 'refus' },
  conformite: { faible: 'complet', moyen: 'complet', eleve: 'complet', critique: 'complet' },
  service_partenaire: { faible: 'complet', moyen: 'masque', eleve: 'refus', critique: 'refus' },
  admin_systeme: { faible: 'refus', moyen: 'refus', eleve: 'refus', critique: 'refus' },
};

const LIGNES = Object.entries(MATRICE_ATTENDUE).flatMap(([roleCode, parNiveau]) =>
  Object.entries(parNiveau).map(([niveau, action]) => ({
    roleCode,
    niveau: niveau as NiveauSens,
    action,
  })),
);

describe('PolicyService — matrice rôle × sensibilité', () => {
  let service: PolicyService;

  beforeEach(async () => {
    const module = await Test.createTestingModule({
      providers: [
        PolicyService,
        {
          provide: PolicyRepository,
          useValue: { chargerMatrice: jest.fn().mockResolvedValue(LIGNES) },
        },
      ],
    }).compile();

    service = module.get(PolicyService);
    await service.onModuleInit();
  });

  it('couvre exactement 24 cases', () => {
    expect(service.matriceComplete()).toHaveLength(24);
  });

  describe.each(Object.keys(MATRICE_ATTENDUE))('rôle %s', (role) => {
    it.each(NIVEAUX)('niveau %s', (niveau) => {
      expect(service.decide(role, niveau)).toBe(MATRICE_ATTENDUE[role][niveau]);
    });
  });

  // --- Refus par défaut ------------------------------------------------------

  it('refuse un rôle inconnu, quel que soit le niveau', () => {
    for (const niveau of NIVEAUX) {
      expect(service.decide('role_invente', niveau)).toBe('refus');
    }
  });

  it('refuse un rôle vide', () => {
    expect(service.decide('', 'faible')).toBe('refus');
  });

  it('refuse quand la case a été retirée de la matrice', () => {
    // Simule une politique partiellement configurée : la case absente ne doit
    // jamais retomber sur une valeur permissive.
    service.chargerDepuis(LIGNES.filter((l) => !(l.roleCode === 'conformite' && l.niveau === 'critique')));
    expect(service.decide('conformite', 'critique')).toBe('refus');
    expect(service.decide('conformite', 'eleve')).toBe('complet');
  });

  it('refuse quand la matrice est vide', () => {
    service.chargerDepuis([]);
    for (const niveau of NIVEAUX) {
      expect(service.decide('conformite', niveau)).toBe('refus');
    }
  });

  it("ne produit jamais 'complet' pour un niveau critique hors conformité", () => {
    for (const role of Object.keys(MATRICE_ATTENDUE)) {
      if (role === 'conformite') {
        continue;
      }
      expect(service.decide(role, 'critique')).toBe('refus');
    }
  });

  // --- Document non analysé --------------------------------------------------

  it('lève NiveauInconnuError quand le niveau est null (-> 423)', () => {
    expect(() => service.decide('conformite', null)).toThrow(NiveauInconnuError);
  });

  it("ne rend jamais 'complet' pour un niveau inconnu, même pour la conformité", () => {
    expect(() => service.decide('conformite', null)).toThrow();
  });
});
