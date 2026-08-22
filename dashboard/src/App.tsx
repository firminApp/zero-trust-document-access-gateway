import { useState } from 'react';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { connecter, deconnecter, jeton, roleCourant } from './api/client';
import Audit from './pages/Audit';
import Cartographie from './pages/Cartographie';
import Sources from './pages/Sources';
import Statistiques from './pages/Statistiques';

export default function App(): JSX.Element {
  const [connecte, setConnecte] = useState(Boolean(jeton()));

  if (!connecte) {
    return <Connexion onConnecte={() => setConnecte(true)} />;
  }

  return (
    <div className="application">
      <aside className="laterale">
        <h1>Zero-Trust Gateway</h1>
        <p className="sous-titre">Supervision</p>

        <nav>
          <NavLink to="/cartographie" className={({ isActive }) => (isActive ? 'actif' : '')}>
            Cartographie
          </NavLink>
          <NavLink to="/statistiques" className={({ isActive }) => (isActive ? 'actif' : '')}>
            Statistiques
          </NavLink>
          <NavLink to="/audit" className={({ isActive }) => (isActive ? 'actif' : '')}>
            Audit
          </NavLink>
          <NavLink to="/sources" className={({ isActive }) => (isActive ? 'actif' : '')}>
            Sources
          </NavLink>
        </nav>

        <div className="pied">
          <div>
            Rôle : <strong>{roleCourant()}</strong>
          </div>
          <button
            style={{ marginTop: 10, width: '100%' }}
            onClick={() => {
              deconnecter();
              setConnecte(false);
            }}
          >
            Se déconnecter
          </button>
        </div>
      </aside>

      <main className="principal">
        <Routes>
          <Route path="/" element={<Navigate to="/cartographie" replace />} />
          <Route path="/cartographie" element={<Cartographie />} />
          <Route path="/statistiques" element={<Statistiques />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="*" element={<Navigate to="/cartographie" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function Connexion({ onConnecte }: { onConnecte: () => void }): JSX.Element {
  const [utilisateur, setUtilisateur] = useState('conformite');
  const [motDePasse, setMotDePasse] = useState('');
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  async function soumettre(evenement: React.FormEvent): Promise<void> {
    evenement.preventDefault();
    setEnCours(true);
    setErreur(null);
    try {
      await connecter(utilisateur, motDePasse);
      onConnecte();
    } catch (exception) {
      setErreur((exception as Error).message);
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="connexion">
      <form onSubmit={(e) => void soumettre(e)}>
        <h1>Zero-Trust Gateway</h1>
        <p>
          Console de supervision. Le journal d&apos;audit et les statistiques sont
          réservés aux rôles de contrôle.
        </p>

        <label>
          Utilisateur
          <input
            value={utilisateur}
            onChange={(e) => setUtilisateur(e.target.value)}
            autoComplete="username"
            required
          />
        </label>

        <label>
          Mot de passe
          <input
            type="password"
            value={motDePasse}
            onChange={(e) => setMotDePasse(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {erreur ? <div className="bandeau echec">{erreur}</div> : null}

        <button type="submit" disabled={enCours}>
          {enCours ? 'Connexion…' : 'Se connecter'}
        </button>
      </form>
    </div>
  );
}
