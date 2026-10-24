import { useState } from 'react';
import { api } from '../api';
import { Brand } from '../App';

// M1 sign-in: accounts are created by a CoSE admin (`cose-cloud create-user`); the app is reached over the HQ
// network or VPN. Google sign-in is M2.
export function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <form className="card" onSubmit={async e => {
        e.preventDefault();
        setBusy(true); setError(null);
        try { await api.login(email, password); onDone(); }
        catch (err) { setError((err as Error).message || 'Sign-in failed'); }
        finally { setBusy(false); }
      }}>
        <Brand />
        <label>Email<input type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} required /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required /></label>
        {error && <div className="err" role="alert">{error}</div>}
        <button className="btn primary" disabled={busy} style={{ justifyContent: 'center' }}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p className="muted" style={{ margin: 0, fontSize: '0.8rem' }}>Accounts are created by your CoSE administrator.</p>
      </form>
    </div>
  );
}
