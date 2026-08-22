import { Injectable, Logger } from '@nestjs/common';
import { Source } from '../common/types';
import { Connecteur } from './connector.interface';
import { GDriveConnector, ConfigurationGDrive } from './gdrive.connector';
import { LocalConnector, ConfigurationLocale } from './local.connector';
import { ConfigurationS3, S3Connector } from './s3.connector';

/**
 * Instancie le connecteur correspondant au type de source.
 *
 * Les instances sont mises en cache par identifiant de source : recréer un
 * client S3 à chaque lecture rouvrirait un pool de connexions par requête.
 */
@Injectable()
export class ConnectorFactory {
  private readonly logger = new Logger(ConnectorFactory.name);
  private readonly cache = new Map<string, Connecteur>();

  pour(source: Source): Connecteur {
    const existant = this.cache.get(source.id);
    if (existant) {
      return existant;
    }

    const connecteur = ConnectorFactory.construire(source);
    this.cache.set(source.id, connecteur);
    this.logger.log(`Connecteur ${source.type} instancié pour « ${source.libelle} »`);
    return connecteur;
  }

  static construire(source: Source): Connecteur {
    switch (source.type) {
      case 's3':
        return new S3Connector(source.configuration as unknown as ConfigurationS3);
      case 'gdrive':
        return new GDriveConnector(source.configuration as unknown as ConfigurationGDrive);
      case 'local':
        return new LocalConnector(source.configuration as unknown as ConfigurationLocale);
      default: {
        // Type de source inconnu : on refuse plutôt que de deviner.
        const type: never = source.type;
        throw new Error(`Type de source non pris en charge : ${String(type)}`);
      }
    }
  }

  vider(): void {
    this.cache.clear();
  }
}
