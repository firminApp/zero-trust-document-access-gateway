/**
 * Audit — journal filtrable et vérification d'intégrité de la chaîne.
 *
 * Le bouton « vérifier l'intégrité » rejoue tout le chaînage côté portail. Un
 * journal qu'on ne peut pas vérifier ne prouve rien : c'est la raison d'être
 * de cette page.
 */

import { useState } from 'react';
import { api } from '../api/client';
import {
  Carte,
  Etat,
  PastilleAction,
  Pastille,
  dateCourte,
  useChargement,
} from '../composants';

interface Filtres {
  document: string;
  utilisateur: string;
  depuis: string;
  jusqua: string;
}

const FILTRES_VIDES: Filtres = { document: '', utilisateur: '', depuis: '', jusqua: '' };

export default function Audit(): JSX.Element {
  const [filtres, setFiltres] = useState<Filtres>(FILTRES_VIDES);
  const [appliques, setAppliques] = useState<Filtres>(FILTRES_VIDES);
  const [page, setPage] = useState(1);

  const { donnees, erreur, enCours } = useChargement(
    () =>
      api.audit({
        document: appliques.document || undefined,
        utilisateur: appliques.utilisateur || undefined,
        depuis: appliques.depuis || undefined,
        jusqua: appliques.jusqua || undefined,
        page: String(page),
        taille: '50',
      }),
    [appliques, page],
  );

  const [verification, setVerification] = useState<{
    intact: boolean;
    premiereRupture: string | null;
    nbEntrees: number;
  } | null>(null);
  const [verificationEnCours, setVerificationEnCours] = useState(false);
  const [erreurVerification, setErreurVerification] = useState<string | null>(null);

  async function verifier(): Promise<void> {
    setVerificationEnCours(true);
    setErreurVerification(null);
    try {
      setVerification(await api.verifierChaine());
    } catch (exception) {
      setErreurVerification((exception as Error).message);
    } finally {
      setVerificationEnCours(false);
    }
  }

  const total = donnees?.total ?? 0;
  const nbPages = Math.max(1, Math.ceil(total / 50));

  return (
    <>
      <h2>Journal d&apos;audit</h2>
      <p className="description">
        Toute requête de lecture y figure, y compris les refus. Le journal est en ajout
        seul et chaque entrée est chaînée à la précédente par empreinte&nbsp;: modifier ou
        supprimer une ligne casse la chaîne à partir d&apos;elle.
      </p>

      <Carte titre="Intégrité de la chaîne">
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <button onClick={() => void verifier()} disabled={verificationEnCours}>
            {verificationEnCours ? 'Vérification…' : "Vérifier l'intégrité de la chaîne"}
          </button>

          {verification ? (
            verification.intact ? (
              <span className="bandeau succes" style={{ margin: 0 }}>
                Chaîne intacte — {verification.nbEntrees} entrée(s) rejouée(s).
              </span>
            ) : (
              <span className="bandeau echec" style={{ margin: 0 }}>
                Chaîne rompue à partir de l&apos;entrée n° {verification.premiereRupture}.
              </span>
            )
          ) : null}

          {erreurVerification ? (
            <span className="bandeau echec" style={{ margin: 0 }}>
              {erreurVerification}
            </span>
          ) : null}
        </div>
      </Carte>

      <div style={{ height: 20 }} />

      <div className="filtres">
        <label>
          Document
          <input
            value={filtres.document}
            placeholder="uuid du document"
            onChange={(e) => setFiltres({ ...filtres, document: e.target.value })}
          />
        </label>
        <label>
          Utilisateur
          <input
            value={filtres.utilisateur}
            placeholder="identifiant"
            onChange={(e) => setFiltres({ ...filtres, utilisateur: e.target.value })}
          />
        </label>
        <label>
          Depuis
          <input
            type="date"
            value={filtres.depuis}
            onChange={(e) => setFiltres({ ...filtres, depuis: e.target.value })}
          />
        </label>
        <label>
          Jusqu&apos;à
          <input
            type="date"
            value={filtres.jusqua}
            onChange={(e) => setFiltres({ ...filtres, jusqua: e.target.value })}
          />
        </label>
        <button
          onClick={() => {
            setPage(1);
            setAppliques(filtres);
          }}
        >
          Filtrer
        </button>
        <button
          onClick={() => {
            setFiltres(FILTRES_VIDES);
            setAppliques(FILTRES_VIDES);
            setPage(1);
          }}
        >
          Réinitialiser
        </button>
      </div>

      <Etat enCours={enCours} erreur={erreur} vide={!donnees}>
        <Carte titre={`${total} entrée(s)`}>
          <table>
            <thead>
              <tr>
                <th>Horodatage</th>
                <th>Utilisateur</th>
                <th>Rôle</th>
                <th>Action</th>
                <th>Politique</th>
                <th>Niveau</th>
                <th>Document</th>
                <th>IP</th>
              </tr>
            </thead>
            <tbody>
              {(donnees?.entrees ?? []).map((entree) => (
                <tr key={entree.id}>
                  <td>{dateCourte(entree.horodatage)}</td>
                  <td>{entree.utilisateurId}</td>
                  <td>{entree.roleEffectif}</td>
                  <td>
                    <span
                      className={`pastille ${entree.action === 'REFUS' ? 'refus' : 'neutre'}`}
                    >
                      {entree.action}
                    </span>
                  </td>
                  <td>
                    <PastilleAction valeur={entree.politiqueAppliquee} />
                  </td>
                  <td>
                    <Pastille valeur={entree.niveauEnCause} />
                  </td>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>
                    {entree.documentId?.slice(0, 8) ?? '—'}
                  </td>
                  <td>{entree.adresseIp ?? '—'}</td>
                </tr>
              ))}
              {donnees && donnees.entrees.length === 0 ? (
                <tr>
                  <td colSpan={8} className="vide">
                    Aucune entrée pour ces filtres.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>

          <div style={{ display: 'flex', gap: 10, marginTop: 14, alignItems: 'center' }}>
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Précédent
            </button>
            <span style={{ color: 'var(--texte-attenue)' }}>
              Page {page} / {nbPages}
            </span>
            <button disabled={page >= nbPages} onClick={() => setPage(page + 1)}>
              Suivant
            </button>
          </div>
        </Carte>
      </Etat>
    </>
  );
}
