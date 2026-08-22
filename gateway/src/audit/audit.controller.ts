import { Controller, Get, Query } from '@nestjs/common';
import { Roles } from '../auth/decorators';
import { AuditService, LigneAudit, ResultatVerification } from './audit.service';

/**
 * Consultation du journal.
 *
 * Réservée aux rôles de contrôle : le journal dit qui a lu quoi, c'est
 * lui-même une donnée sensible. `admin_systeme` y a accès pour l'exploitation
 * — il administre le portail mais ne peut lire aucun document.
 */
@Controller('api/v1/audit')
@Roles('conformite', 'admin_systeme')
export class AuditController {
  constructor(private readonly audit: AuditService) {}

  @Get()
  async rechercher(
    @Query('document') documentId?: string,
    @Query('utilisateur') utilisateurId?: string,
    @Query('depuis') depuis?: string,
    @Query('jusqua') jusqua?: string,
    @Query('page') page?: string,
    @Query('taille') taille?: string,
  ): Promise<{ total: number; entrees: LigneAudit[] }> {
    return this.audit.rechercher({
      documentId,
      utilisateurId,
      depuis,
      jusqua,
      page: page ? Number(page) : undefined,
      taille: taille ? Number(taille) : undefined,
    });
  }

  /** Rejoue le chaînage complet et rend le point de rupture éventuel. */
  @Get('verification')
  async verification(): Promise<ResultatVerification> {
    return this.audit.verifyChain();
  }
}
