import { AuditService, EMPREINTE_GENESE } from './audit.service';

/**
 * T-04 — le chaînage détecte l'altération.
 *
 * Le calcul d'empreinte est une fonction pure : on peut donc construire une
 * chaîne en mémoire, l'altérer, et vérifier la détection sans base de données.
 * Le comportement en base (règles `DO INSTEAD NOTHING`, transaction
 * SERIALIZABLE) est couvert par les tests d'intégration.
 */

interface Maillon {
  id: string;
  utilisateurId: string;
  roleEffectif: string;
  documentId: string | null;
  action: string;
  politiqueAppliquee: string | null;
  horodatageIso: string;
  empreintePrecedente: string | null;
  empreinte: string;
}

function construireChaine(longueur: number): Maillon[] {
  const chaine: Maillon[] = [];
  let precedente: string | null = null;

  for (let index = 0; index < longueur; index += 1) {
    const base = {
      utilisateurId: `agent${index}`,
      roleEffectif: 'support_n1',
      documentId: `doc-${index}`,
      action: index % 3 === 0 ? 'REFUS' : 'LECTURE',
      politiqueAppliquee: index % 3 === 0 ? 'refus' : 'masque',
      horodatageIso: new Date(Date.UTC(2026, 0, 1, 0, 0, index)).toISOString(),
    };
    const empreinte = AuditService.calculerEmpreinte({
      ...base,
      empreintePrecedente: precedente,
    });
    chaine.push({ id: String(index + 1), ...base, empreintePrecedente: precedente, empreinte });
    precedente = empreinte;
  }
  return chaine;
}

/** Rejoue la vérification sur une chaîne en mémoire. */
function verifier(chaine: Maillon[]): { intact: boolean; premiereRupture: string | null } {
  let precedente: string | null = null;
  for (const maillon of chaine) {
    if ((maillon.empreintePrecedente ?? null) !== precedente) {
      return { intact: false, premiereRupture: maillon.id };
    }
    const attendue = AuditService.calculerEmpreinte({
      empreintePrecedente: precedente,
      utilisateurId: maillon.utilisateurId,
      roleEffectif: maillon.roleEffectif,
      documentId: maillon.documentId,
      action: maillon.action,
      politiqueAppliquee: maillon.politiqueAppliquee,
      horodatageIso: maillon.horodatageIso,
    });
    if (attendue !== maillon.empreinte) {
      return { intact: false, premiereRupture: maillon.id };
    }
    precedente = maillon.empreinte;
  }
  return { intact: true, premiereRupture: null };
}

describe('AuditService — chaînage cryptographique', () => {
  it('ancre la chaîne sur SHA-256 de la chaîne vide', () => {
    expect(EMPREINTE_GENESE).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    );
  });

  it('produit une empreinte déterministe', () => {
    const parametres = {
      empreintePrecedente: null,
      utilisateurId: 'awa',
      roleEffectif: 'conformite',
      documentId: 'doc-1',
      action: 'LECTURE',
      politiqueAppliquee: 'complet',
      horodatageIso: '2026-01-01T00:00:00.000Z',
    };
    expect(AuditService.calculerEmpreinte(parametres)).toBe(
      AuditService.calculerEmpreinte(parametres),
    );
  });

  it('change d’empreinte si un seul champ change', () => {
    const base = {
      empreintePrecedente: null,
      utilisateurId: 'awa',
      roleEffectif: 'conformite',
      documentId: 'doc-1',
      action: 'LECTURE',
      politiqueAppliquee: 'complet',
      horodatageIso: '2026-01-01T00:00:00.000Z',
    };
    const reference = AuditService.calculerEmpreinte(base);

    expect(AuditService.calculerEmpreinte({ ...base, utilisateurId: 'moussa' })).not.toBe(reference);
    expect(AuditService.calculerEmpreinte({ ...base, roleEffectif: 'support_n1' })).not.toBe(reference);
    expect(AuditService.calculerEmpreinte({ ...base, action: 'REFUS' })).not.toBe(reference);
    expect(AuditService.calculerEmpreinte({ ...base, politiqueAppliquee: 'refus' })).not.toBe(reference);
    expect(AuditService.calculerEmpreinte({ ...base, documentId: 'doc-2' })).not.toBe(reference);
    expect(
      AuditService.calculerEmpreinte({ ...base, horodatageIso: '2026-01-01T00:00:01.000Z' }),
    ).not.toBe(reference);
  });

  it('valide une chaîne intacte', () => {
    expect(verifier(construireChaine(50))).toEqual({ intact: true, premiereRupture: null });
  });

  it("détecte la modification du rôle d'une entrée", () => {
    const chaine = construireChaine(10);
    chaine[4].roleEffectif = 'conformite'; // élévation de privilège maquillée
    expect(verifier(chaine)).toEqual({ intact: false, premiereRupture: '5' });
  });

  it('détecte un refus réécrit en lecture autorisée', () => {
    const chaine = construireChaine(10);
    chaine[6].action = 'LECTURE';
    chaine[6].politiqueAppliquee = 'complet';
    expect(verifier(chaine).intact).toBe(false);
  });

  it('détecte la suppression d’une entrée intermédiaire', () => {
    const chaine = construireChaine(10);
    chaine.splice(5, 1);
    const resultat = verifier(chaine);
    expect(resultat.intact).toBe(false);
    // Le maillon suivant pointe vers une empreinte qui n'existe plus.
    expect(resultat.premiereRupture).toBe('7');
  });

  it('détecte la réécriture d’une empreinte sans recalculer les suivantes', () => {
    const chaine = construireChaine(10);
    chaine[3].empreinte = 'f'.repeat(64);
    expect(verifier(chaine)).toEqual({ intact: false, premiereRupture: '4' });
  });

  it("signale la PREMIÈRE rupture, pas la dernière", () => {
    const chaine = construireChaine(10);
    chaine[2].utilisateurId = 'intrus';
    chaine[7].utilisateurId = 'intrus';
    expect(verifier(chaine).premiereRupture).toBe('3');
  });

  it('traite une chaîne vide comme intacte', () => {
    expect(verifier([])).toEqual({ intact: true, premiereRupture: null });
  });
});
