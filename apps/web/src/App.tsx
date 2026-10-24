import { useEffect, useState } from 'react';
import { Cpu, LogOut, Monitor, Moon, Plane, Sprout, Sun, Tractor, Wind, Building2, MessageCircle } from 'lucide-react';
import { api, AuthError, type Edition, type Me } from './api';
import { AgentPanel } from './components/AgentPanel';
import { HqView } from './components/HqView';
import { Login } from './components/Login';
import { PlannedView } from './components/PlannedView';
import { XseedView } from './components/XseedView';
import { applyTheme, storedTheme, type ThemeChoice } from './lib/theme';

const ICONS: Record<string, typeof Cpu> = { hq: Building2, xseed: Sprout, rover: Tractor, drone: Plane, sense: Wind };

function route(): string {
  return window.location.hash.replace(/^#\/?/, '').split('/')[0] || 'hq';
}

export function Brand() {
  return (
    <div className="brand">
      <svg width="34" height="34" viewBox="0 0 64 64" aria-hidden>
        <defs><radialGradient id="bg" cx="40%" cy="35%" r="70%"><stop offset="0" stopColor="#54C9BA" />
          <stop offset=".45" stopColor="#3FB6A8" /><stop offset=".8" stopColor="#3B6EA5" /><stop offset="1" stopColor="#2F5985" /></radialGradient></defs>
        <circle cx="32" cy="32" r="28" fill="url(#bg)" />
      </svg>
      <div><div className="t1">CoSE Cloud</div><div className="t2">Collaborative Science Environment</div></div>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [unreachable, setUnreachable] = useState<string | null>(null);
  const [editions, setEditions] = useState<Edition[]>([]);
  const [page, setPage] = useState(route);
  const [theme, setTheme] = useState<ThemeChoice>(storedTheme);
  const [agentOpen, setAgentOpen] = useState(() => window.matchMedia?.('(min-width: 1101px)').matches ?? true);

  useEffect(() => { applyTheme(theme); }, [theme]);
  useEffect(() => {
    const onHash = () => setPage(route());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const loadMe = () => api.me().then(m => { setMe(m); setNeedLogin(false); setUnreachable(null); })
    .catch(e => { if (e instanceof AuthError) setNeedLogin(true); else setUnreachable(String(e.message || e)); });
  const loadAll = () => {
    setUnreachable(null);
    loadMe();
    api.editions().then(setEditions).catch(e => setUnreachable(String(e.message || e)));
  };
  useEffect(loadAll, []);

  if (unreachable) return (
    <div className="login"><div className="card" role="alert" style={{ maxWidth: 420 }}>
      <Brand />
      <p>CoSE Cloud cannot reach its server right now ({unreachable}).</p>
      <button className="btn primary" onClick={loadAll}>Try again</button>
    </div></div>
  );
  if (needLogin) return <Login onDone={loadMe} />;
  if (!me || !editions.length) return <div className="login"><p className="muted">Loading CoSE Cloud…</p></div>;

  const edition = editions.find(e => e.id === page) || editions[0];
  const nextTheme: Record<ThemeChoice, ThemeChoice> = { system: 'light', light: 'dark', dark: 'system' };
  const ThemeIcon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor;

  return (
    <div className={`app${agentOpen ? '' : ' agent-closed'}`}>
      <aside className="rail">
        <Brand />
        <nav aria-label="Editions">
          <div className="navhead">Editions</div>
          {editions.map(e => {
            const Icon = ICONS[e.id] || Cpu;
            return (
              <a key={e.id} href={`#/${e.id}`} className={`navlink${e.id === edition.id ? ' active' : ''}`}
                aria-current={e.id === edition.id ? 'page' : undefined}>
                <Icon size={17} aria-hidden />
                <span>{e.name}<span className="sub">{e.id === 'hq' ? 'everything, merged' : e.products.join(', ')}</span></span>
                {e.status === 'planned' && <span className="tag">planned</span>}
              </a>
            );
          })}
        </nav>
        <div className="rail-foot">
          <div><b>{me.org.name}</b><div className="muted">{me.user.email} · {me.user.role}</div>
            <div className="muted">plan: {me.entitlements.tier} · agent: {me.entitlements.llm_mode}</div></div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn" onClick={() => setTheme(nextTheme[theme])} aria-label={`Theme: ${theme}`}><ThemeIcon size={14} /> {theme}</button>
            <button className="btn" onClick={() => api.logout().then(() => setNeedLogin(true))}><LogOut size={14} /> Sign out</button>
          </div>
        </div>
      </aside>

      <main className="main">
        {edition.status === 'planned' ? <PlannedView edition={edition} />
          : edition.id === 'xseed' ? <XseedView edition={edition} />
          : <HqView edition={edition} editions={editions} />}
      </main>

      <AgentPanel edition={edition.id} open={agentOpen} onClose={() => setAgentOpen(false)} />
      {!agentOpen && (
        <button className="btn primary agent-toggle" style={{ display: 'inline-flex' }} onClick={() => setAgentOpen(true)}>
          <MessageCircle size={16} /> CoSE_Agent</button>
      )}
    </div>
  );
}
