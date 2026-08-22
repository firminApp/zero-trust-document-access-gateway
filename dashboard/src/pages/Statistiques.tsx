/**
 * Statistiques — entités par type et par niveau, historique des scans.
 *
 * La ventilation par type d'entité est le point important : un compteur global
 * masque les angles morts. On affiche donc toujours le détail, jamais
 * seulement le total.
 */

import { api } from '../api/client';
import { Carte, Etat, Indicateur, dateCourte, useChargement } from '../composants';

export default function Statistiques(): JSX.Element {
  const { donnees, erreur, enCours } = useChargement(() => api.statistiques());
  const politiques = useChargement(() => api.politiques());

  return (
    <>
      <h2>Statistiques</h2>
      <p className="description">
        Volumétrie de la détection, méthode par méthode, et historique des campagnes de
        scan. Les valeurs des entités ne sont jamais stockées : seuls leur type, leur
        niveau et leur position le sont.
      </p>

      <Etat enCours={enCours} erreur={erreur} vide={!donnees}>
        {donnees ? (
          <>
            <div className="grille">
              <Carte titre="Entités détectées">
                <Indicateur valeur={donnees.entites.total} />
              </Carte>
              <Carte titre="Par méthode de détection">
                <table>
                  <tbody>
                    {Object.entries(donnees.entites.parMethode).map(([methode, total]) => (
                      <tr key={methode}>
                        <td>{methode}</td>
                        <td className="numerique">{total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Carte>
              <Carte titre="Accès journalisés">
                <Indicateur valeur={donnees.audit.total} />
              </Carte>
            </div>

            <Carte titre="Entités par type et par niveau">
              <table>
                <thead>
                  <tr>
                    <th>Type d&apos;entité</th>
                    <th>Niveau</th>
                    <th className="numerique">Occurrences</th>
                  </tr>
                </thead>
                <tbody>
                  {donnees.entites.parType.map((entite) => (
                    <tr key={`${entite.typeEntite}:${entite.niveau}`}>
                      <td>{entite.typeEntite}</td>
                      <td>
                        <span className={`pastille ${entite.niveau}`}>{entite.niveau}</span>
                      </td>
                      <td className="numerique">{entite.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Carte>

            <div style={{ height: 16 }} />

            <Carte titre="Décisions de politique appliquées">
              <table>
                <thead>
                  <tr>
                    <th>Action</th>
                    <th className="numerique">Occurrences</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(donnees.audit.parPolitique).map(([action, total]) => (
                    <tr key={action}>
                      <td>
                        <span className={`pastille ${action}`}>{action}</span>
                      </td>
                      <td className="numerique">{total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Carte>

            <div style={{ height: 16 }} />

            <Carte titre="Historique des scans">
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Démarré</th>
                    <th>Terminé</th>
                    <th className="numerique">Listés</th>
                    <th className="numerique">Nouveaux</th>
                    <th className="numerique">Échecs</th>
                  </tr>
                </thead>
                <tbody>
                  {donnees.scans.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="vide">
                        Aucun scan enregistré.
                      </td>
                    </tr>
                  ) : (
                    donnees.scans.map((scan, index) => (
                      <tr key={`${scan.source}-${index}`}>
                        <td>{scan.source}</td>
                        <td>{dateCourte(scan.demarreLe)}</td>
                        <td>{dateCourte(scan.termineLe)}</td>
                        <td className="numerique">{scan.nbListes}</td>
                        <td className="numerique">{scan.nbNouveaux}</td>
                        <td className="numerique">{scan.nbEchecs}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </Carte>

            <div style={{ height: 16 }} />

            <Carte titre="Matrice de politique en vigueur">
              <Etat
                enCours={politiques.enCours}
                erreur={politiques.erreur}
                vide={!politiques.donnees}
              >
                <MatricePolitique lignes={politiques.donnees?.matrice ?? []} />
              </Etat>
            </Carte>
          </>
        ) : null}
      </Etat>
    </>
  );
}

const NIVEAUX = ['faible', 'moyen', 'eleve', 'critique'] as const;

function MatricePolitique({
  lignes,
}: {
  lignes: Array<{ role: string; niveau: string; action: string }>;
}): JSX.Element {
  const roles = [...new Set(lignes.map((l) => l.role))].sort();
  const index = new Map(lignes.map((l) => [`${l.role}:${l.niveau}`, l.action]));

  return (
    <table>
      <thead>
        <tr>
          <th>Rôle</th>
          {NIVEAUX.map((niveau) => (
            <th key={niveau}>{niveau}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {roles.map((role) => (
          <tr key={role}>
            <td>{role}</td>
            {NIVEAUX.map((niveau) => {
              // Case absente = refus : c'est la règle du refus par défaut,
              // rendue visible telle quelle dans la console.
              const action = index.get(`${role}:${niveau}`) ?? 'refus';
              return (
                <td key={niveau}>
                  <span className={`pastille ${action}`}>{action}</span>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
