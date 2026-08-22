import type { drive_v3 } from 'googleapis';
import {
  Connecteur,
  Ressource,
  RessourceIntrouvableError,
  SourceIndisponibleError,
} from './connector.interface';

export interface ConfigurationGDrive {
  folderId: string;
  /** JSON du compte de service ; à défaut, lu depuis GDRIVE_SERVICE_ACCOUNT_JSON. */
  serviceAccountJson?: string;
}

const PORTEE = ['https://www.googleapis.com/auth/drive.readonly'];

/**
 * Connecteur Google Drive, via un compte de service.
 *
 * Le compte de service est le pendant Drive du principe S3 : seul le portail
 * le détient, et les utilisateurs n'ont plus de partage direct sur les
 * dossiers concernés.
 */
export class GDriveConnector implements Connecteur {
  private readonly folderId: string;
  private drive: drive_v3.Drive | null = null;
  private readonly identifiants: string;

  constructor(configuration: ConfigurationGDrive) {
    this.folderId = configuration.folderId;
    this.identifiants =
      configuration.serviceAccountJson ?? process.env.GDRIVE_SERVICE_ACCOUNT_JSON ?? '';
  }

  private async client(): Promise<drive_v3.Drive> {
    if (this.drive) {
      return this.drive;
    }
    if (!this.identifiants) {
      throw new SourceIndisponibleError('gdrive', 'compte de service non configuré');
    }

    try {
      // Import paresseux : `googleapis` est un module très volumineux, et la
      // plupart des déploiements n'utilisent que S3 et le disque local.
      const { google } = await import('googleapis');
      const auth = new google.auth.GoogleAuth({
        credentials: JSON.parse(this.identifiants),
        scopes: PORTEE,
      });
      this.drive = google.drive({ version: 'v3', auth });
      return this.drive;
    } catch (erreur) {
      throw new SourceIndisponibleError('gdrive', erreur);
    }
  }

  /** Parcours récursif paginé par `pageToken`. */
  async *lister(prefixe?: string): AsyncIterable<Ressource> {
    const drive = await this.client();
    yield* this.parcourir(drive, prefixe || this.folderId, '');
  }

  private async *parcourir(
    drive: drive_v3.Drive,
    dossierId: string,
    chemin: string,
  ): AsyncIterable<Ressource> {
    let pageToken: string | undefined;

    do {
      let reponse;
      try {
        reponse = await drive.files.list({
          q: `'${dossierId}' in parents and trashed = false`,
          fields: 'nextPageToken, files(id, name, mimeType, size, modifiedTime)',
          pageSize: 200,
          pageToken,
          supportsAllDrives: true,
          includeItemsFromAllDrives: true,
        });
      } catch (erreur) {
        throw new SourceIndisponibleError('gdrive', erreur);
      }

      for (const fichier of reponse.data.files ?? []) {
        if (!fichier.id || !fichier.name) {
          continue;
        }
        const chemincomplet = chemin ? `${chemin}/${fichier.name}` : fichier.name;

        if (fichier.mimeType === 'application/vnd.google-apps.folder') {
          yield* this.parcourir(drive, fichier.id, chemincomplet);
          continue;
        }

        yield {
          // La clé porte l'identifiant : c'est lui qui reste stable si le
          // fichier est renommé, et c'est par lui que `lire()` accède.
          cle: `${fichier.id}:${chemincomplet}`,
          taille: Number(fichier.size ?? 0),
          dateModification: new Date(fichier.modifiedTime ?? 0),
          typeMime: fichier.mimeType ?? undefined,
        };
      }

      pageToken = reponse.data.nextPageToken ?? undefined;
    } while (pageToken);
  }

  async lire(cle: string): Promise<Buffer> {
    const drive = await this.client();
    const identifiant = cle.split(':')[0];

    try {
      const reponse = await drive.files.get(
        { fileId: identifiant, alt: 'media', supportsAllDrives: true },
        { responseType: 'arraybuffer' },
      );
      return Buffer.from(reponse.data as ArrayBuffer);
    } catch (erreur) {
      const statut = (erreur as { code?: number }).code;
      if (statut === 404) {
        throw new RessourceIntrouvableError(cle);
      }
      throw new SourceIndisponibleError('gdrive', erreur);
    }
  }

  async ecrire(cle: string, contenu: Buffer): Promise<void> {
    const drive = await this.client();
    const nom = cle.includes(':') ? cle.split(':').slice(1).join(':') : cle;
    const { Readable } = await import('node:stream');

    try {
      await drive.files.create({
        requestBody: { name: nom, parents: [this.folderId] },
        media: { body: Readable.from(contenu) },
        supportsAllDrives: true,
      });
    } catch (erreur) {
      throw new SourceIndisponibleError('gdrive', erreur);
    }
  }
}
