/**
 * Client HTTP du tableau de bord.
 *
 * Le tableau de bord n'appelle que le portail, jamais le moteur IA ni la base.
 * Il ne consomme que des agrégats : types, niveaux, compteurs. Aucune route
 * exposant du contenu de document n'est utilisée ici — et c'est volontaire :
 * une console de supervision qui affiche les données qu'elle surveille est une
 * seconde fuite.
 */

const BASE = import.meta.env.VITE_API_URL ?? '';

const CLE_JETON = 'ztg.jeton';
const CLE_ROLE = 'ztg.role';

export interface Jetons {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export function jeton(): string | null {
  return localStorage.getItem(CLE_JETON);
}

export function roleCourant(): string | null {
  return localStorage.getItem(CLE_ROLE);
}

export function deconnecter(): void {
  localStorage.removeItem(CLE_JETON);
  localStorage.removeItem(CLE_ROLE);
}

export class ErreurApi extends Error {
  constructor(
    readonly statut: number,
    message: string,
  ) {
    super(message);
  }
}

async function appeler<T>(chemin: string, options: RequestInit = {}): Promise<T> {
  const entetes: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) ?? {}),
  };

  const jetonCourant = jeton();
  if (jetonCourant) {
    entetes.Authorization = `Bearer ${jetonCourant}`;
  }

  const reponse = await fetch(`${BASE}${chemin}`, { ...options, headers: entetes });

  if (reponse.status === 401) {
    deconnecter();
    throw new ErreurApi(401, 'Session expirée, reconnexion nécessaire');
  }
  if (!reponse.ok) {
    const detail = await reponse.text().catch(() => '');
    throw new ErreurApi(reponse.status, detail || `Erreur HTTP ${reponse.status}`);
  }
  return (await reponse.json()) as T;
}

export async function connecter(utilisateur: string, motDePasse: string): Promise<void> {
  const jetons = await appeler<Jetons>('/api/v1/auth/token', {
    method: 'POST',
    body: JSON.stringify({ utilisateur, motDePasse }),
  });

  localStorage.setItem(CLE_JETON, jetons.accessToken);
  const charge = JSON.parse(atob(jetons.accessToken.split('.')[1] ?? 'e30='));
  localStorage.setItem(CLE_ROLE, charge.role ?? 'inconnu');
}

// --- Types de réponse --------------------------------------------------------

export interface Statistiques {
  documents: {
    total: number;
    parStatut: Record<string, number>;
    parNiveau: Record<string, number>;
    parSource: Array<{
      source: string;
      type: string;
      total: number;
      niveaux: Record<string, number>;
    }>;
  };
  entites: {
    total: number;
    parType: Array<{ typeEntite: string; niveau: string; total: number }>;
    parMethode: Record<string, number>;
  };
  scans: Array<{
    source: string;
    demarreLe: string;
    termineLe: string | null;
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

export interface EntreeAudit {
  id: string;
  horodatage: string;
  utilisateurId: string;
  roleEffectif: string;
  documentId: string | null;
  action: string;
  politiqueAppliquee: string | null;
  niveauEnCause: string | null;
  adresseIp: string | null;
  details: Record<string, unknown> | null;
}

export interface Source {
  id: string;
  type: string;
  libelle: string;
  frequenceCron: string;
  dernierScan: string | null;
  actif: boolean;
}

export interface LignePolitique {
  role: string;
  niveau: string;
  action: string;
}

// --- Points d'appel ----------------------------------------------------------

export const api = {
  statistiques: (): Promise<Statistiques> => appeler('/api/v1/statistiques'),

  politiques: (): Promise<{ matrice: LignePolitique[] }> => appeler('/api/v1/politiques'),

  sources: (): Promise<Source[]> => appeler('/api/v1/sources'),

  declencherScan: (id: string): Promise<{ planifie: boolean }> =>
    appeler(`/api/v1/sources/${id}/scan`, { method: 'POST' }),

  audit: (filtres: Record<string, string | undefined>): Promise<{
    total: number;
    entrees: EntreeAudit[];
  }> => {
    const parametres = new URLSearchParams();
    for (const [cle, valeur] of Object.entries(filtres)) {
      if (valeur) {
        parametres.set(cle, valeur);
      }
    }
    return appeler(`/api/v1/audit?${parametres.toString()}`);
  },

  verifierChaine: (): Promise<{
    intact: boolean;
    premiereRupture: string | null;
    nbEntrees: number;
  }> => appeler('/api/v1/audit/verification'),
};
