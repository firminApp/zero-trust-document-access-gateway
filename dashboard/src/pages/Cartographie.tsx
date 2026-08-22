/**
 * Cartographie — répartition des documents par source et par niveau.
 *
 * C'est la vue qui répond à « où sont nos données personnelles, et à quel
 * degré de sensibilité ». Elle n'affiche aucun contenu ni aucune valeur : des
 * compteurs, des sources, des niveaux.
 */

import { api } from '../api/client';
import {
  BarreNiveaux,
  Carte,
  Etat,
  Indicateur,
  Legende,
  useChargement,
} from '../composants';

const NIVEAUX = ['faible', 'moyen', 'eleve', 'critique', 'non_analyse'];

export default function Cartographie(): JSX.Element {
  const { donnees, erreur, enCours } = useChargement(() => api.statistiques());

  return (
    <>
      <h2>Cartographie</h2>
      <p className="description">
        Répartition du patrimoine documentaire par source de stockage et par niveau de
        sensibilité maximal détecté. Un document reste « non analysé » tant que le moteur
        n&apos;a pas conclu — et dans cet état, le portail refuse sa restitution (HTTP&nbsp;423).
      </p>

      <Etat enCours={enCours} erreur={erreur} vide={!donnees}>
        {donnees ? (
          <>
            <div className="grille">
              <Carte titre="Documents catalogués">
                <Indicateur valeur={donnees.documents.total} />
              </Carte>
              <Carte titre="Entités détectées">
                <Indicateur valeur={donnees.entites.total} />
              </Carte>
              <Carte titre="Documents critiques">
                <Indicateur valeur={donnees.documents.parNiveau.critique ?? 0} />
              </Carte>
              <Carte titre="Taux d'échec d'analyse">
                <Indicateur
                  valeur={(donnees.tauxEchec * 100).toFixed(1)}
                  unite="%"
                />
              </Carte>
            </div>

            <Carte titre="Par source">
              <table>
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Type</th>
                    <th className="numerique">Documents</th>
                    <th style={{ width: '40%' }}>Répartition par niveau</th>
                  </tr>
                </thead>
                <tbody>
                  {donnees.documents.parSource.map((source) => (
                    <tr key={source.source}>
                      <td>{source.source}</td>
                      <td>
                        <span className="pastille neutre">{source.type}</span>
                      </td>
                      <td className="numerique">{source.total}</td>
                      <td>
                        <BarreNiveaux niveaux={source.niveaux} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Legende entrees={NIVEAUX} />
            </Carte>

            <div className="grille" style={{ marginTop: 16 }}>
              <Carte titre="Par statut de traitement">
                <table>
                  <tbody>
                    {Object.entries(donnees.documents.parStatut).map(([statut, total]) => (
                      <tr key={statut}>
                        <td>{statut}</td>
                        <td className="numerique">{total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Carte>

              <Carte titre="Par niveau maximal">
                <table>
                  <tbody>
                    {NIVEAUX.filter((n) => donnees.documents.parNiveau[n]).map((niveau) => (
                      <tr key={niveau}>
                        <td>
                          <span className={`pastille ${niveau}`}>{niveau}</span>
                        </td>
                        <td className="numerique">{donnees.documents.parNiveau[niveau]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Carte>
            </div>
          </>
        ) : null}
      </Etat>
    </>
  );
}
