import { Controller, Get } from '@nestjs/common';
import { PolicyService } from '../policy/policy.service';
import { Statistiques, StatistiquesService } from './statistiques.service';

@Controller('api/v1')
export class StatistiquesController {
  constructor(
    private readonly statistiques: StatistiquesService,
    private readonly politique: PolicyService,
  ) {}

  @Get('statistiques')
  async agregats(): Promise<Statistiques> {
    return this.statistiques.calculer();
  }

  /** Matrice de politique en vigueur — affichée telle quelle par le tableau de bord. */
  @Get('politiques')
  matrice(): { matrice: ReturnType<PolicyService['matriceComplete']> } {
    return { matrice: this.politique.matriceComplete() };
  }
}
