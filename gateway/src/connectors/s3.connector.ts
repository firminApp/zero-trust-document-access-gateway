import {
  GetObjectCommand,
  ListObjectsV2Command,
  NoSuchKey,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';
import {
  Connecteur,
  Ressource,
  RessourceIntrouvableError,
  SourceIndisponibleError,
} from './connector.interface';

export interface ConfigurationS3 {
  bucket: string;
  prefixe?: string;
  endpoint?: string;
  region?: string;
}

/**
 * Connecteur S3 (AWS ou MinIO).
 *
 * Ce connecteur est le **seul** détenteur des identifiants du bucket dans tout
 * le système : c'est la parade documentée à la limite assumée du projet
 * (contrôle applicatif, stockage non chiffré). Le moteur IA ne reçoit que des
 * octets, jamais ces identifiants.
 */
export class S3Connector implements Connecteur {
  private readonly client: S3Client;
  private readonly bucket: string;
  private readonly prefixe: string;

  constructor(configuration: ConfigurationS3) {
    this.bucket = configuration.bucket;
    this.prefixe = configuration.prefixe ?? '';
    this.client = new S3Client({
      region: configuration.region ?? process.env.S3_REGION ?? 'us-east-1',
      endpoint: configuration.endpoint ?? process.env.S3_ENDPOINT,
      // MinIO n'expose pas de DNS par bucket : l'adressage par chemin est requis.
      forcePathStyle: true,
      credentials: {
        accessKeyId: process.env.S3_ACCESS_KEY ?? '',
        secretAccessKey: process.env.S3_SECRET_KEY ?? '',
      },
    });
  }

  /** Pagination par `ContinuationToken` : une page en mémoire à la fois. */
  async *lister(prefixe?: string): AsyncIterable<Ressource> {
    let jeton: string | undefined;

    do {
      let reponse;
      try {
        reponse = await this.client.send(
          new ListObjectsV2Command({
            Bucket: this.bucket,
            Prefix: prefixe ?? this.prefixe,
            ContinuationToken: jeton,
            MaxKeys: 1000,
          }),
        );
      } catch (erreur) {
        throw new SourceIndisponibleError(`s3://${this.bucket}`, erreur);
      }

      for (const objet of reponse.Contents ?? []) {
        if (!objet.Key || objet.Key.endsWith('/')) {
          continue; // pseudo-répertoire
        }
        yield {
          cle: objet.Key,
          taille: objet.Size ?? 0,
          dateModification: objet.LastModified ?? new Date(0),
        };
      }

      jeton = reponse.IsTruncated ? reponse.NextContinuationToken : undefined;
    } while (jeton);
  }

  async lire(cle: string): Promise<Buffer> {
    try {
      const reponse = await this.client.send(
        new GetObjectCommand({ Bucket: this.bucket, Key: cle }),
      );
      const corps = reponse.Body;
      if (!corps) {
        throw new RessourceIntrouvableError(cle);
      }
      const morceaux: Buffer[] = [];
      for await (const morceau of corps as AsyncIterable<Uint8Array>) {
        morceaux.push(Buffer.from(morceau));
      }
      return Buffer.concat(morceaux);
    } catch (erreur) {
      if (erreur instanceof NoSuchKey || (erreur as { name?: string }).name === 'NoSuchKey') {
        throw new RessourceIntrouvableError(cle);
      }
      if (erreur instanceof RessourceIntrouvableError) {
        throw erreur;
      }
      throw new SourceIndisponibleError(`s3://${this.bucket}`, erreur);
    }
  }

  async ecrire(cle: string, contenu: Buffer): Promise<void> {
    try {
      await this.client.send(
        new PutObjectCommand({ Bucket: this.bucket, Key: cle, Body: contenu }),
      );
    } catch (erreur) {
      throw new SourceIndisponibleError(`s3://${this.bucket}`, erreur);
    }
  }
}
