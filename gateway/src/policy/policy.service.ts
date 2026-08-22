import {
  Injectable,
  Logger,
  OnApplicationShutdown,
  OnModuleInit,
} from '@nestjs/common';
import { PolicyRepository } from './policy.repository';
import { ActionAcces, NiveauSens } from '../common/types';

/**
 * Point de décision de politique (PDP au sens du NIST SP 800-207).
 *
 * Règle unique et non négociable : **refus par défaut**. Une case absente de
 * la matrice, un rôle inconnu, un niveau inconnu — tout ce qui n'est pas une
 * autorisation explicitement enregistrée est un refus. Aucun chemin de ce
 * fichier ne doit pouvoir produire `complet` sans avoir lu la case
 * correspondante en base.
 */

/** Levée quand le document n'est pas encore analysé -> HTTP 423. */
export class NiveauInconnuError extends Error {
  constructor() {
    super(
      "Le niveau de sensibilité du document n'est pas connu : " +
        'la politique est inapplicable, la lecture est refusée.',
    );
    this.name = 'NiveauInconnuError';
  }
}

/** Intervalle de reprise quand la matrice n'a pas pu être chargée. */
const DELAI_REPRISE_MS = 15_000;

@Injectable()
export class PolicyService implements OnModuleInit, OnApplicationShutdown {
  private readonly logger = new Logger(PolicyService.name);
  private matrice = new Map<string, ActionAcces>();
  private reprise: NodeJS.Timeout | null = null;

  constructor(private readonly repository: PolicyRepository) {}

  /**
   * Charge la matrice au démarrage — sans empêcher le service de démarrer.
   *
   * Sur une base non encore migrée (`make up` avant `make seed`), la lecture
   * échoue. Refuser de démarrer créerait un blocage circulaire : les
   * migrations s'appliquent depuis cette image. On démarre donc avec une
   * matrice **vide**, ce qui signifie « refus de tout » — l'état sûr — et on
   * réessaie jusqu'à ce que la matrice soit disponible.
   */
  async onModuleInit(): Promise<void> {
    try {
      await this.recharger();
    } catch (erreur) {
      this.logger.error(
        `Matrice de politique illisible (${(erreur as Error).message}). ` +
          "Toutes les lectures sont refusées jusqu'à son chargement. " +
          'Avez-vous exécuté `make seed` ?',
      );
      this.programmerReprise();
    }
  }

  private programmerReprise(): void {
    if (this.reprise) {
      return;
    }
    this.reprise = setInterval(() => {
      void this.recharger()
        .then(() => {
          this.logger.log('Matrice de politique chargée après reprise');
          this.annulerReprise();
        })
        .catch(() => undefined);
    }, DELAI_REPRISE_MS);
    this.reprise.unref();
  }

  private annulerReprise(): void {
    if (this.reprise) {
      clearInterval(this.reprise);
      this.reprise = null;
    }
  }

  onApplicationShutdown(): void {
    this.annulerReprise();
  }

  async recharger(): Promise<void> {
    const lignes = await this.repository.chargerMatrice();
    const matrice = new Map<string, ActionAcces>();
    for (const ligne of lignes) {
      matrice.set(PolicyService.cle(ligne.roleCode, ligne.niveau), ligne.action);
    }
    this.matrice = matrice;
  }

  /** Alimente la matrice sans base — utilisé par les tests unitaires. */
  chargerDepuis(lignes: Array<{ roleCode: string; niveau: NiveauSens; action: ActionAcces }>): void {
    this.matrice = new Map(
      lignes.map((l) => [PolicyService.cle(l.roleCode, l.niveau), l.action]),
    );
  }

  private static cle(role: string, niveau: NiveauSens): string {
    return `${role}:${niveau}`;
  }

  /**
   * Décide de l'action applicable à un rôle face à un niveau de sensibilité.
   *
   * @throws NiveauInconnuError si le document n'a pas encore été analysé.
   */
  decide(role: string, niveauMax: NiveauSens | null): ActionAcces {
    if (niveauMax === null || niveauMax === undefined) {
      // On ignore ce que contient le document : servir « en attendant »
      // recréerait exactement la faille que le projet supprime.
      throw new NiveauInconnuError();
    }

    const politique = this.matrice.get(PolicyService.cle(role, niveauMax));
    if (politique === undefined) {
      this.logger.warn(
        `Aucune politique pour ${role}:${niveauMax} — refus par défaut appliqué`,
      );
      return 'refus';
    }
    return politique;
  }

  /** Vue complète de la matrice, pour le tableau de bord et les tests. */
  matriceComplete(): Array<{ role: string; niveau: NiveauSens; action: ActionAcces }> {
    return [...this.matrice.entries()].map(([cle, action]) => {
      const [role, niveau] = cle.split(':');
      return { role, niveau: niveau as NiveauSens, action };
    });
  }
}
