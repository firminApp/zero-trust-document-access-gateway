import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ConnectorFactory } from './connector.factory';
import { RessourceIntrouvableError } from './connector.interface';
import { LocalConnector } from './local.connector';

describe('LocalConnector', () => {
  let racine: string;
  let connecteur: LocalConnector;

  beforeEach(async () => {
    racine = await mkdtemp(join(tmpdir(), 'ztg-'));
    await mkdir(join(racine, 'contrats/2026'), { recursive: true });
    await writeFile(join(racine, 'note.txt'), 'sans donnée personnelle');
    await writeFile(join(racine, 'contrats/bail.txt'), 'Awa Diouf');
    await writeFile(join(racine, 'contrats/2026/avenant.txt'), 'Kofi Mensah');
    connecteur = new LocalConnector({ chemin: racine });
  });

  afterEach(async () => {
    await rm(racine, { recursive: true, force: true });
  });

  async function collecter(): Promise<string[]> {
    const cles: string[] = [];
    for await (const ressource of connecteur.lister()) {
      cles.push(ressource.cle);
    }
    return cles.sort();
  }

  it('liste récursivement, avec des clés relatives normalisées', async () => {
    expect(await collecter()).toEqual([
      'contrats/2026/avenant.txt',
      'contrats/bail.txt',
      'note.txt',
    ]);
  });

  it('expose la taille et la date de modification', async () => {
    for await (const ressource of connecteur.lister()) {
      expect(ressource.taille).toBeGreaterThan(0);
      expect(ressource.dateModification.getTime()).toBeGreaterThan(0);
    }
  });

  it('lit le contenu d’un fichier', async () => {
    expect((await connecteur.lire('contrats/bail.txt')).toString()).toBe('Awa Diouf');
  });

  it('écrit puis relit', async () => {
    await connecteur.ecrire('sortie/protege.txt', Buffer.from('A•• D••••'));
    expect((await connecteur.lire('sortie/protege.txt')).toString()).toBe('A•• D••••');
  });

  it('signale une ressource absente', async () => {
    await expect(connecteur.lire('inexistant.txt')).rejects.toBeInstanceOf(
      RessourceIntrouvableError,
    );
  });

  it("refuse de sortir de la racine déclarée", async () => {
    // Sans cette garde, le portail deviendrait un lecteur de fichiers
    // arbitraire, authentifié et journalisé — mais arbitraire.
    await expect(connecteur.lire('../../etc/passwd')).rejects.toBeInstanceOf(
      RessourceIntrouvableError,
    );
  });

  it('ignore un répertoire absent au lieu d’échouer', async () => {
    const vide = new LocalConnector({ chemin: join(racine, 'nexiste-pas') });
    const cles: string[] = [];
    for await (const ressource of vide.lister()) {
      cles.push(ressource.cle);
    }
    expect(cles).toEqual([]);
  });

  it('liste paresseusement : le premier élément arrive sans tout parcourir', async () => {
    // Preuve que `lister()` est bien un générateur : on interrompt après un
    // élément, sur une arborescence volumineuse (piège n°3).
    const gros = await mkdtemp(join(tmpdir(), 'ztg-gros-'));
    try {
      await Promise.all(
        Array.from({ length: 500 }, (_, i) => writeFile(join(gros, `f${i}.txt`), 'x')),
      );
      const paresseux = new LocalConnector({ chemin: gros });

      let vus = 0;
      for await (const _ressource of paresseux.lister()) {
        vus += 1;
        break;
      }
      expect(vus).toBe(1);
    } finally {
      await rm(gros, { recursive: true, force: true });
    }
  });
});

describe('ConnectorFactory', () => {
  const base = {
    id: 'src-1',
    libelle: 'Test',
    frequenceCron: '0 2 * * *',
    dernierScan: null,
    actif: true,
  };

  it('instancie le connecteur local', () => {
    const connecteur = ConnectorFactory.construire({
      ...base,
      type: 'local',
      configuration: { chemin: tmpdir() },
    });
    expect(connecteur).toBeInstanceOf(LocalConnector);
  });

  it('met en cache les instances par source', () => {
    const fabrique = new ConnectorFactory();
    const source = { ...base, type: 'local' as const, configuration: { chemin: tmpdir() } };
    expect(fabrique.pour(source)).toBe(fabrique.pour(source));
  });

  it('refuse un type de source inconnu', () => {
    expect(() =>
      ConnectorFactory.construire({
        ...base,
        type: 'ftp' as never,
        configuration: {},
      }),
    ).toThrow(/non pris en charge/);
  });
});
