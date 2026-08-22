import { Inject, Injectable } from '@nestjs/common';
import { Pool } from 'pg';
import { PG_POOL } from '../db/database.module';

export interface Statistiques {
  documents: {
    total: number;
    parStatut: Record<string, number>;
    parNiveau: Record<string, number>;
    parSource: Array<{ source: string; type: string; total: number; niveaux: Record<string, number> }>;
  };
  entites: {
    total: number;
    parType: Array<{ typeEntite: string; niveau: string; total: number }>;
    parMethode: Record<string, number>;
  };
  scans: Array<{
    source: string;
    demarreLe: Date;
    termineLe: Date | null;
    nbListes: number;
    nbNouveaux: number;
    nbEchecs: number;
  }>;
  audit: {
    total: number;
    parAction: Record<string, number>;
    parPolitique: Record<string, number>;
  };
  tauxEchec: number;
}

/**
 * Agrégats du tableau de bord (M7).
 *
 * Toutes les requêtes portent sur des compteurs, des types et des niveaux.
 * Aucune ne renvoie de valeur d'entité ni de contenu de document : le tableau
 * de bord n'a pas à en connaître.
 */
@Injectable()
export class StatistiquesService {
  constructor(@Inject(PG_POOL) private readonly pool: Pool) {}

  async calculer(): Promise<Statistiques> {
    const [statuts, niveaux, parSource, entitesType, entitesMethode, scans, auditAction, auditPolitique] =
      await Promise.all([
        this.pool.query<{ statut: string; total: string }>(
          'SELECT statut, count(*)::text AS total FROM document GROUP BY statut',
        ),
        this.pool.query<{ niveau_max: string | null; total: string }>(
          'SELECT niveau_max, count(*)::text AS total FROM document GROUP BY niveau_max',
        ),
        this.pool.query<{
          libelle: string;
          type: string;
          niveau_max: string | null;
          total: string;
        }>(
          `SELECT s.libelle, s.type::text, d.niveau_max::text, count(*)::text AS total
             FROM document d JOIN source s ON s.id = d.source_id
            GROUP BY s.libelle, s.type, d.niveau_max
            ORDER BY s.libelle`,
        ),
        this.pool.query<{ type_entite: string; niveau_sensibilite: string; total: string }>(
          `SELECT type_entite, niveau_sensibilite::text, count(*)::text AS total
             FROM entite_detectee
            GROUP BY type_entite, niveau_sensibilite
            ORDER BY count(*) DESC`,
        ),
        this.pool.query<{ methode: string; total: string }>(
          'SELECT methode::text, count(*)::text AS total FROM entite_detectee GROUP BY methode',
        ),
        this.pool.query<{
          libelle: string;
          demarre_le: Date;
          termine_le: Date | null;
          nb_listes: number;
          nb_nouveaux: number;
          nb_echecs: number;
        }>(
          `SELECT s.libelle, e.demarre_le, e.termine_le, e.nb_listes, e.nb_nouveaux, e.nb_echecs
             FROM scan_execution e JOIN source s ON s.id = e.source_id
            ORDER BY e.demarre_le DESC LIMIT 30`,
        ),
        this.pool.query<{ action: string; total: string }>(
          'SELECT action, count(*)::text AS total FROM journal_audit GROUP BY action',
        ),
        this.pool.query<{ politique_appliquee: string | null; total: string }>(
          `SELECT politique_appliquee::text, count(*)::text AS total
             FROM journal_audit GROUP BY politique_appliquee`,
        ),
      ]);

    const parStatut = StatistiquesService.compter(statuts.rows, 'statut');
    const totalDocuments = Object.values(parStatut).reduce((a, b) => a + b, 0);
    const nbEchecs = parStatut['echec'] ?? 0;

    const sources = new Map<
      string,
      { source: string; type: string; total: number; niveaux: Record<string, number> }
    >();
    for (const ligne of parSource.rows) {
      const courant = sources.get(ligne.libelle) ?? {
        source: ligne.libelle,
        type: ligne.type,
        total: 0,
        niveaux: {},
      };
      const total = Number(ligne.total);
      courant.total += total;
      courant.niveaux[ligne.niveau_max ?? 'non_analyse'] = total;
      sources.set(ligne.libelle, courant);
    }

    const entitesParType = entitesType.rows.map((r) => ({
      typeEntite: r.type_entite,
      niveau: r.niveau_sensibilite,
      total: Number(r.total),
    }));

    return {
      documents: {
        total: totalDocuments,
        parStatut,
        parNiveau: StatistiquesService.compter(niveaux.rows, 'niveau_max', 'non_analyse'),
        parSource: [...sources.values()],
      },
      entites: {
        total: entitesParType.reduce((a, e) => a + e.total, 0),
        parType: entitesParType,
        parMethode: StatistiquesService.compter(entitesMethode.rows, 'methode'),
      },
      scans: scans.rows.map((r) => ({
        source: r.libelle,
        demarreLe: r.demarre_le,
        termineLe: r.termine_le,
        nbListes: r.nb_listes,
        nbNouveaux: r.nb_nouveaux,
        nbEchecs: r.nb_echecs,
      })),
      audit: {
        total: auditAction.rows.reduce((a, r) => a + Number(r.total), 0),
        parAction: StatistiquesService.compter(auditAction.rows, 'action'),
        parPolitique: StatistiquesService.compter(
          auditPolitique.rows,
          'politique_appliquee',
          'sans_objet',
        ),
      },
      tauxEchec: totalDocuments === 0 ? 0 : Number((nbEchecs / totalDocuments).toFixed(4)),
    };
  }

  private static compter(
    lignes: Array<Record<string, unknown>>,
    cle: string,
    defaut = 'inconnu',
  ): Record<string, number> {
    const resultat: Record<string, number> = {};
    for (const ligne of lignes) {
      const nom = (ligne[cle] as string | null) ?? defaut;
      resultat[nom] = Number(ligne.total);
    }
    return resultat;
  }
}
