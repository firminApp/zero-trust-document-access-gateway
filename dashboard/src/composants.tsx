/** Composants partagés du tableau de bord. */

import { ReactNode, useEffect, useState } from 'react';

export const COULEURS_NIVEAU: Record<string, string> = {
  faible: '#22c55e',
  moyen: '#eab308',
  eleve: '#f97316',
  critique: '#ef4444',
  non_analyse: '#64748b',
  inconnu: '#64748b',
};

export function Pastille({ valeur }: { valeur: string | null }): JSX.Element {
  const classe = valeur && COULEURS_NIVEAU[valeur] ? valeur : 'neutre';
  return <span className={`pastille ${classe}`}>{valeur ?? '—'}</span>;
}

export function PastilleAction({ valeur }: { valeur: string | null }): JSX.Element {
  const connues = ['complet', 'masque', 'pseudonymise', 'refus'];
  const classe = valeur && connues.includes(valeur) ? valeur : 'neutre';
  return <span className={`pastille ${classe}`}>{valeur ?? '—'}</span>;
}

export function Carte({
  titre,
  children,
}: {
  titre: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <div className="carte">
      <h3>{titre}</h3>
      {children}
    </div>
  );
}

export function Indicateur({
  valeur,
  unite,
}: {
  valeur: number | string;
  unite?: string;
}): JSX.Element {
  return (
    <div className="indicateur">
      {valeur}
      {unite ? <span className="unite">{unite}</span> : null}
    </div>
  );
}

/** Barre empilée : répartition d'un total par niveau de sensibilité. */
export function BarreNiveaux({
  niveaux,
}: {
  niveaux: Record<string, number>;
}): JSX.Element {
  const total = Object.values(niveaux).reduce((a, b) => a + b, 0) || 1;
  const ordre = ['faible', 'moyen', 'eleve', 'critique', 'non_analyse'];

  return (
    <div className="barre-empilee">
      {ordre
        .filter((niveau) => niveaux[niveau])
        .map((niveau) => (
          <span
            key={niveau}
            title={`${niveau} : ${niveaux[niveau]}`}
            style={{
              width: `${(niveaux[niveau] / total) * 100}%`,
              background: COULEURS_NIVEAU[niveau],
            }}
          />
        ))}
    </div>
  );
}

export function Legende({ entrees }: { entrees: string[] }): JSX.Element {
  return (
    <div className="legende">
      {entrees.map((entree) => (
        <span key={entree}>
          <i style={{ background: COULEURS_NIVEAU[entree] ?? '#64748b' }} />
          {entree}
        </span>
      ))}
    </div>
  );
}

/** Chargement de données avec états explicites (chargement / erreur / prêt). */
export function useChargement<T>(
  charger: () => Promise<T>,
  dependances: unknown[] = [],
): { donnees: T | null; erreur: string | null; enCours: boolean; recharger: () => void } {
  const [donnees, setDonnees] = useState<T | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(true);
  const [compteur, setCompteur] = useState(0);

  useEffect(() => {
    let annule = false;
    setEnCours(true);
    setErreur(null);

    charger()
      .then((resultat) => {
        if (!annule) {
          setDonnees(resultat);
        }
      })
      .catch((exception: Error) => {
        if (!annule) {
          setErreur(exception.message);
        }
      })
      .finally(() => {
        if (!annule) {
          setEnCours(false);
        }
      });

    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependances, compteur]);

  return { donnees, erreur, enCours, recharger: () => setCompteur((c) => c + 1) };
}

export function Etat({
  enCours,
  erreur,
  vide,
  children,
}: {
  enCours: boolean;
  erreur: string | null;
  vide?: boolean;
  children: ReactNode;
}): JSX.Element {
  if (enCours) {
    return <div className="chargement">Chargement…</div>;
  }
  if (erreur) {
    return <div className="bandeau echec">{erreur}</div>;
  }
  if (vide) {
    return <div className="vide">Aucune donnée.</div>;
  }
  return <>{children}</>;
}

export function dateCourte(valeur: string | null): string {
  if (!valeur) {
    return '—';
  }
  return new Date(valeur).toLocaleString('fr-FR', {
    dateStyle: 'short',
    timeStyle: 'medium',
  });
}
