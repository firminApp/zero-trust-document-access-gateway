import { Body, Controller, Get, Ip, Param, ParseUUIDPipe, Post } from '@nestjs/common';
import { IsIn, IsNotEmpty, IsObject, IsOptional, IsString } from 'class-validator';
import { AuditService } from '../audit/audit.service';
import { Roles, Utilisateur } from '../auth/decorators';
import { CatalogService } from '../catalog/catalog.service';
import { ACTIONS_AUDIT, Source, TYPES_SOURCE, TypeSource, UtilisateurJwt } from '../common/types';
import { FileTaches } from '../scheduler/queue';

export class CreationSourceDto {
  @IsIn(TYPES_SOURCE as unknown as string[])
  type!: TypeSource;

  @IsString()
  @IsNotEmpty()
  libelle!: string;

  @IsObject()
  configuration!: Record<string, unknown>;

  @IsOptional()
  @IsString()
  frequenceCron?: string;
}

/**
 * Administration des sources.
 *
 * Déclarer une source et déclencher un scan sont des actes d'exploitation :
 * ils sont réservés à `admin_systeme` — qui, en contrepartie, ne peut lire
 * aucun document (matrice §M1). Les deux opérations sont journalisées comme
 * `CONFIG` et `SCAN`.
 */
@Controller('api/v1/sources')
export class SourcesController {
  constructor(
    private readonly catalogue: CatalogService,
    private readonly file: FileTaches,
    private readonly audit: AuditService,
  ) {}

  @Get()
  async lister(): Promise<Source[]> {
    return this.catalogue.sources();
  }

  @Post()
  @Roles('admin_systeme')
  async creer(
    @Body() corps: CreationSourceDto,
    @Utilisateur() utilisateur: UtilisateurJwt,
    @Ip() ip: string,
  ): Promise<Source> {
    const source = await this.catalogue.creerSource(corps);

    await this.audit.append({
      utilisateurId: utilisateur.sub,
      roleEffectif: utilisateur.role,
      action: ACTIONS_AUDIT.CONFIG,
      adresseIp: ip ?? null,
      details: { operation: 'creation_source', sourceId: source.id, type: source.type },
    });

    return source;
  }

  @Post(':id/scan')
  @Roles('admin_systeme')
  async scanner(
    @Param('id', ParseUUIDPipe) id: string,
    @Utilisateur() utilisateur: UtilisateurJwt,
    @Ip() ip: string,
  ): Promise<{ planifie: boolean; sourceId: string }> {
    const source = await this.catalogue.source(id);
    if (!source) {
      await this.audit.append({
        utilisateurId: utilisateur.sub,
        roleEffectif: utilisateur.role,
        action: ACTIONS_AUDIT.REFUS,
        adresseIp: ip ?? null,
        details: { motif: 'source_inconnue', sourceId: id },
      });
      return { planifie: false, sourceId: id };
    }

    await this.file.planifierScan({ sourceId: id, declencheur: 'manuel' });
    await this.audit.append({
      utilisateurId: utilisateur.sub,
      roleEffectif: utilisateur.role,
      action: ACTIONS_AUDIT.SCAN,
      adresseIp: ip ?? null,
      details: { operation: 'scan_manuel', sourceId: id, source: source.libelle },
    });

    return { planifie: true, sourceId: id };
  }
}
