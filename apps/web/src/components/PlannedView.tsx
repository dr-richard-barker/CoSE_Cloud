import { Construction } from 'lucide-react';
import type { Edition } from '../api';

// A product edition whose hardware cannot send data yet: say so, and say what it needs.
export function PlannedView({ edition }: { edition: Edition }) {
  return (
    <div className="stack">
      <div className="pagehead">
        <div><h1>{edition.name}</h1><p>{edition.tagline}</p></div>
        <span className="badge planned">planned</span>
      </div>
      <div className="banner" role="note"><Construction size={16} />
        <div><b>No data source yet.</b> This edition is a shell until the hardware can send data. Nothing here is
          simulated or estimated: it shows no readings at all.</div></div>
      <div className="grid2">
        <div className="card"><h2>Data source (as designed)</h2><p style={{ marginBottom: 0 }}>{edition.data_source}</p></div>
        <div className="card"><h2>What it needs</h2><p style={{ marginBottom: 0 }}>{edition.needs}</p></div>
      </div>
      <div className="card">
        <h2>Meanwhile</h2>
        <p className="muted" style={{ marginBottom: 0 }}>CoSE_Agent can still search past experiments and describe the
          metric registry. The HQ edition shows every device that is reporting.</p>
      </div>
    </div>
  );
}
