/**
 * Sources — inventaire et déclenchement manuel de scan.
 *
 * Le déclenchement est réservé au rôle `admin_systeme` côté portail. Le bouton
 * est masqué pour les autres, mais c'est le portail qui décide : l'interface
 * n'est jamais le point de contrôle.
 */

import { useState } from 'react';
import { api, roleCourant } from '../api/client';
import { Carte, Etat, dateCourte, useChargement } from '../composants';

export default function Sources(): JSX.Element {
  const { donnees, erreur, enCours, recharger } = useChargement(() => api.sources());
  const [message, setMessage] = useState<{ texte: string; succes: boolean } | null>(null);
  const [enAttente, setEnAttente] = useState<string | null>(null);

  const estAdministrateur = roleCourant() === 'admin_systeme';

  async function declencher(id: string, libelle: string): Promise<void> {
    setEnAttente(id);
    setMessage(null);
    try {
      await api.declencherScan(id);
      setMessage({ texte: `Scan planifié pour « ${libelle} ».`, succes: true });
      recharger();
    } catch (exception) {
      setMessage({ texte: (exception as Error).message, succes: false });
    } finally {
      setEnAttente(null);
    }
  }

  return (
    <>
      <h2>Sources de stockage</h2>
      <p className="description">
        Les identifiants d&apos;accès à ces sources ne sont détenus que par le compte de
        service du portail. C&apos;est cette exclusivité qui ferme la voie d&apos;accès
        directe au stockage.
      </p>

      {message ? (
        <div className={`bandeau ${message.succes ? 'succes' : 'echec'}`}>{message.texte}</div>
      ) : null}

      {!estAdministrateur ? (
        <div className="bandeau" style={{ color: 'var(--texte-attenue)' }}>
          Le déclenchement manuel d&apos;un scan est réservé au rôle
          <strong> admin_systeme</strong>.
        </div>
      ) : null}

      <Etat enCours={enCours} erreur={erreur} vide={!donnees?.length}>
        <Carte titre={`${donnees?.length ?? 0} source(s)`}>
          <table>
            <thead>
              <tr>
                <th>Libellé</th>
                <th>Type</th>
                <th>Planification</th>
                <th>Dernier scan</th>
                <th>État</th>
                {estAdministrateur ? <th /> : null}
              </tr>
            </thead>
            <tbody>
              {(donnees ?? []).map((source) => (
                <tr key={source.id}>
                  <td>{source.libelle}</td>
                  <td>
                    <span className="pastille neutre">{source.type}</span>
                  </td>
                  <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {source.frequenceCron}
                  </td>
                  <td>{dateCourte(source.dernierScan)}</td>
                  <td>
                    <span className={`pastille ${source.actif ? 'complet' : 'refus'}`}>
                      {source.actif ? 'actif' : 'inactif'}
                    </span>
                  </td>
                  {estAdministrateur ? (
                    <td>
                      <button
                        disabled={enAttente === source.id || !source.actif}
                        onClick={() => void declencher(source.id, source.libelle)}
                      >
                        {enAttente === source.id ? 'Planification…' : 'Scanner'}
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </Carte>
      </Etat>
    </>
  );
}
