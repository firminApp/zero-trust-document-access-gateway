import { CatalogService } from './catalog.service';

/**
 * Invariant §2 : aucune valeur d'entité personnelle en clair en base.
 * `empreinteValeur` est la barrière — c'est le seul point de passage.
 */
describe('CatalogService — hachage des valeurs', () => {
  it('produit une empreinte SHA-256 hexadécimale de 64 caractères', () => {
    const empreinte = CatalogService.empreinteValeur('Awa Diouf', 'sel');
    expect(empreinte).toMatch(/^[0-9a-f]{64}$/);
  });

  it('ne laisse transparaître aucune trace de la valeur', () => {
    const empreinte = CatalogService.empreinteValeur('SN91SN0100152000048500000765', 'sel');
    expect(empreinte).not.toContain('SN91');
    expect(empreinte).not.toContain('0765');
  });

  it('est déterministe', () => {
    expect(CatalogService.empreinteValeur('Awa Diouf', 'sel')).toBe(
      CatalogService.empreinteValeur('Awa Diouf', 'sel'),
    );
  });

  it('normalise la casse, les accents et les espaces', () => {
    // Sans cela, « Awa DIOUF » et « awa diouf » compteraient pour deux
    // personnes distinctes dans les statistiques.
    const reference = CatalogService.empreinteValeur('Awa Diouf', 'sel');
    expect(CatalogService.empreinteValeur('AWA  DIOUF ', 'sel')).toBe(reference);
    expect(CatalogService.empreinteValeur('awa diouf', 'sel')).toBe(reference);
  });

  it('distingue deux valeurs différentes', () => {
    expect(CatalogService.empreinteValeur('Awa Diouf', 'sel')).not.toBe(
      CatalogService.empreinteValeur('Awa Dioup', 'sel'),
    );
  });

  it('dépend du sel serveur', () => {
    // Sans sel, un dictionnaire de patronymes ouest-africains suffirait à
    // inverser le catalogue (ADR n°6).
    expect(CatalogService.empreinteValeur('Awa Diouf', 'sel-a')).not.toBe(
      CatalogService.empreinteValeur('Awa Diouf', 'sel-b'),
    );
  });

  it("hache le contenu d'un document indépendamment du sel", () => {
    const empreinte = CatalogService.empreinteContenu(Buffer.from('contenu'));
    expect(empreinte).toMatch(/^[0-9a-f]{64}$/);
    expect(CatalogService.empreinteContenu(Buffer.from('contenu'))).toBe(empreinte);
    expect(CatalogService.empreinteContenu(Buffer.from('contenu '))).not.toBe(empreinte);
  });
});
