import { useEffect, useMemo, useRef, useState } from 'react';
import embed, { type Result } from 'vega-embed';
import { expressionInterpreter } from 'vega-interpreter';
import type { VegaSpec } from '../api';
import { vegaConfig } from '../chartTheme';
import { unsafeSpecKey } from '../lib/safety';
import { useMode } from '../lib/theme';
import { ProvenanceBadges } from './ProvenanceBadge';

export const DATA_NAME = 'points';   // services/src/cose_cloud/agent/charts.py DATA_NAME

type Row = { ts: string; series: string; short: string; value: number | null };

interface Props {
  spec: VegaSpec;
  // Live dashboards push new rows into the chart's named dataset instead of re-fetching it.
  liveRows?: Row[];
  label?: string;
}

// Renders a server-built Vega-Lite spec with the theme's validated series palette, and refuses any spec that
// carries a data URL or link. A data table under every chart is the non-colour way to read it.
export function VegaChart({ spec, liveRows, label }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const view = useRef<Result | null>(null);
  const mode = useMode();
  const [error, setError] = useState<string | null>(null);
  const bad = useMemo(() => unsafeSpecKey(spec), [spec]);
  const pushed = useRef(0);

  useEffect(() => {
    if (!ref.current || bad) return;
    let cancelled = false;
    pushed.current = 0;
    // ast + interpreter: no eval/new Function, so the page's Content-Security-Policy can forbid them
    embed(ref.current, spec as never, { actions: false, renderer: 'svg', config: vegaConfig(mode) as never,
      ast: true, expr: expressionInterpreter as never,
      tooltip: { theme: mode === 'dark' ? 'dark' : 'light' } })
      .then(r => { if (cancelled) r.finalize(); else { view.current = r; setError(null); } })
      .catch(e => setError(String(e?.message || e)));
    return () => { cancelled = true; view.current?.finalize(); view.current = null; };
  }, [spec, mode, bad]);

  // Vega's "container" width follows window resizes only; panels opening and closing resize the column too.
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    let frame = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    });
    ro.observe(el);
    return () => { cancelAnimationFrame(frame); ro.disconnect(); };
  }, []);

  useEffect(() => {
    const v = view.current?.view;
    if (!v || !liveRows || liveRows.length <= pushed.current) return;
    const fresh = liveRows.slice(pushed.current);
    pushed.current = liveRows.length;
    v.insert(DATA_NAME, fresh).runAsync().catch(() => { /* chart replaced meanwhile */ });
  }, [liveRows]);

  const rows = ((spec.data as { values?: Row[] } | undefined)?.values || []).concat(liveRows || []);
  if (bad) return <div className="chart" role="alert">This chart was blocked: it referred to outside data ({bad}).</div>;
  return (
    <figure className="chart" aria-label={label || 'chart'} style={{ margin: 0 }}>
      <div className="charthead"><ProvenanceBadges kinds={spec.usermeta?.provenance || []} /></div>
      <div ref={ref} />
      {error && <div className="muted" role="alert">Chart error: {error}</div>}
      <details>
        <summary>Data table ({rows.length} rows)</summary>
        <div className="datatable tablewrap">
          <table>
            <thead><tr><th>Time (UTC)</th><th>Series</th><th>Value</th></tr></thead>
            <tbody>{rows.slice(-500).map((r, i) => (
              <tr key={i}><td className="mono">{r.ts}</td><td>{r.series}</td><td className="mono">{r.value ?? '—'}</td></tr>))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
