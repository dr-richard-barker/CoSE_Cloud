import { useEffect, useState } from 'react';
import type { Mode } from '../chartTheme';

export type ThemeChoice = 'system' | 'light' | 'dark';
const KEY = 'cose-theme';

export function storedTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch { return 'system'; }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === 'system') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', choice);
  try { if (choice === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, choice); } catch { /* private mode */ }
  window.dispatchEvent(new Event('cose-theme'));
}

function currentMode(): Mode {
  const t = document.documentElement.getAttribute('data-theme');
  if (t === 'light' || t === 'dark') return t;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// The resolved light/dark mode, updating on the toggle and on the OS setting.
export function useMode(): Mode {
  const [mode, setMode] = useState<Mode>(currentMode);
  useEffect(() => {
    const update = () => setMode(currentMode());
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    mq?.addEventListener?.('change', update);
    window.addEventListener('cose-theme', update);
    return () => { mq?.removeEventListener?.('change', update); window.removeEventListener('cose-theme', update); };
  }, []);
  return mode;
}
