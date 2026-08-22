import { Logger, ValidationPipe } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

/**
 * Point d'entrée de la passerelle (conteneur `passerelle`, port 3000).
 *
 * C'est le seul service exposé aux applications clientes. Le moteur IA ne
 * publie aucun port : toute lecture de document transite nécessairement par ce
 * processus, ce qui est la condition même du modèle « refus par défaut ».
 */
async function demarrer(): Promise<void> {
  const application = await NestFactory.create(AppModule, {
    logger: ['error', 'warn', 'log'],
  });

  application.useGlobalPipes(
    new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }),
  );
  application.enableCors({
    origin: process.env.CORS_ORIGINE?.split(',') ?? true,
    exposedHeaders: [
      'X-Politique-Appliquee',
      'X-Niveau-Max-Detecte',
      'X-Document-Id',
      'X-Audit-Id',
    ],
  });
  application.enableShutdownHooks();

  const port = Number(process.env.PORT ?? 3000);
  await application.listen(port, '0.0.0.0');
  new Logger('Portail').log(`Portail d'accès à l'écoute sur le port ${port}`);
}

void demarrer();
