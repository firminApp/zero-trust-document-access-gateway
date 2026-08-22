import {
  Controller,
  Get,
  HttpStatus,
  Ip,
  Param,
  ParseUUIDPipe,
  Query,
  Res,
} from '@nestjs/common';
import { Response } from 'express';
import { CatalogService } from '../catalog/catalog.service';
import { NiveauSens, StatutDoc, UtilisateurJwt } from '../common/types';
import { Utilisateur } from '../auth/decorators';
import { DocumentsService } from './documents.service';

@Controller('api/v1/documents')
export class DocumentsController {
  constructor(
    private readonly documents: DocumentsService,
    private readonly catalogue: CatalogService,
  ) {}

  @Get()
  async lister(
    @Query('source') source?: string,
    @Query('statut') statut?: StatutDoc,
    @Query('niveau') niveau?: NiveauSens,
    @Query('page') page?: string,
    @Query('taille') taille?: string,
  ): Promise<unknown> {
    return this.catalogue.lister({
      sourceId: source,
      statut,
      niveau,
      page: page ? Number(page) : undefined,
      taille: taille ? Number(taille) : undefined,
    });
  }

  @Get(':id/metadonnees')
  async metadonnees(
    @Param('id', ParseUUIDPipe) id: string,
    @Utilisateur() utilisateur: UtilisateurJwt,
    @Ip() ip: string,
  ): Promise<unknown> {
    return this.documents.metadonnees(id, { utilisateur, adresseIp: ip ?? null });
  }

  /**
   * Restitution du contenu — l'unique porte de lecture des documents.
   *
   * Le flux n'est écrit qu'après l'appel à `AuditService.append()`, effectué
   * dans le service : la trace précède toujours la donnée.
   */
  @Get(':id/contenu')
  async contenu(
    @Param('id', ParseUUIDPipe) id: string,
    @Utilisateur() utilisateur: UtilisateurJwt,
    @Ip() ip: string,
    @Res() reponse: Response,
    @Query('format') format?: string,
  ): Promise<void> {
    const restitution = await this.documents.restituer(id, {
      utilisateur,
      adresseIp: ip ?? null,
      format: format === 'texte' ? 'texte' : 'original',
    });

    reponse
      .status(HttpStatus.OK)
      .setHeader('Content-Type', restitution.typeMime)
      .setHeader('Content-Length', String(restitution.contenu.length))
      .setHeader('X-Politique-Appliquee', restitution.politiqueAppliquee)
      .setHeader('X-Niveau-Max-Detecte', restitution.niveauMax)
      .setHeader('X-Document-Id', restitution.documentId)
      .setHeader('X-Audit-Id', restitution.auditId)
      .setHeader(
        'Content-Disposition',
        `inline; filename="${restitution.nomFichier.replace(/"/g, '')}"`,
      )
      .send(restitution.contenu);
  }
}
