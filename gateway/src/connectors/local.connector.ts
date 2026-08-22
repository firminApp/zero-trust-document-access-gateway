import { createReadStream } from 'node:fs';
import { opendir, stat, mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { Logger } from '@nestjs/common';
import {
  Connecteur,
  Ressource,
  RessourceIntrouvableError,
  SourceIndisponibleError,
} from './connector.interface';

export interface ConfigurationLocale {
  chemin: string;
}

/** Lecture d'une arborescence de fichiers locale ou montée (NFS, volume). */
export class LocalConnector implements Connecteur {
  private readonly logger = new Logger(LocalConnector.name);
  private readonly racine: string;

  constructor(configuration: ConfigurationLocale) {
    this.racine = resolve(configuration.chemin);
  }

  /** Parcours récursif paresseux : un seul répertoire ouvert à la fois. */
  async *lister(prefixe = ''): AsyncIterable<Ressource> {
    const depart = this.resoudre(prefixe || '.');
    yield* this.parcourir(depart);
  }

  private async *parcourir(repertoire: string): AsyncIterable<Ressource> {
    let dossier;
    try {
      dossier = await opendir(repertoire);
    } catch (erreur) {
      const code = (erreur as NodeJS.ErrnoException).code;
      if (code === 'ENOENT') {
        this.logger.warn(`Répertoire absent, ignoré : ${repertoire}`);
        return;
      }
      throw new SourceIndisponibleError(repertoire, erreur);
    }

    for await (const entree of dossier) {
      const chemin = join(repertoire, entree.name);
      if (entree.isDirectory()) {
        yield* this.parcourir(chemin);
        continue;
      }
      if (!entree.isFile()) {
        continue;
      }

      const infos = await stat(chemin);
      yield {
        cle: relative(this.racine, chemin).split(sep).join('/'),
        taille: infos.size,
        dateModification: infos.mtime,
      };
    }
  }

  async lire(cle: string): Promise<Buffer> {
    const chemin = this.resoudre(cle);
    try {
      const morceaux: Buffer[] = [];
      for await (const morceau of createReadStream(chemin)) {
        morceaux.push(morceau as Buffer);
      }
      return Buffer.concat(morceaux);
    } catch (erreur) {
      if ((erreur as NodeJS.ErrnoException).code === 'ENOENT') {
        throw new RessourceIntrouvableError(cle);
      }
      throw new SourceIndisponibleError(this.racine, erreur);
    }
  }

  async ecrire(cle: string, contenu: Buffer): Promise<void> {
    const chemin = this.resoudre(cle);
    await mkdir(dirname(chemin), { recursive: true });
    await writeFile(chemin, contenu);
  }

  /**
   * Résout une clé sous la racine en refusant toute évasion.
   *
   * Une clé « ../../etc/passwd » venue du catalogue ne doit pas permettre de
   * lire hors du périmètre déclaré de la source : le portail deviendrait un
   * lecteur de fichiers arbitraire authentifié.
   */
  private resoudre(cle: string): string {
    const cible = resolve(this.racine, cle);
    if (cible !== this.racine && !cible.startsWith(this.racine + sep)) {
      throw new RessourceIntrouvableError(cle);
    }
    return cible;
  }
}
