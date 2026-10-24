import { useEffect, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { api, type Device, type Edition, type Experiment } from '../api';
import { ago, localTime } from '../lib/format';
import { TOOLS } from '../tools';
import { Catalog } from './Catalog';
import { ProvenanceBadge } from './ProvenanceBadge';

const EDITION_OF: Record<string, string> = { xseed: 'xseed', 'ground-rover': 'rover', drone: 'drone', sense: 'sense' };

export function HqView({ edition, editions }: { edition: Edition; editions: Edition[] }) {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  useEffect(() => {
    api.devices().then(setDevices).catch(() => setDevices([]));
    api.experiments().then(setExperiments).catch(() => {});
  }, []);

  return (
    <div className="stack">
      <div className="pagehead">
        <div><h1>{edition.name}</h1><p>{edition.tagline}</p></div>
      </div>

      <div className="card">
        <div className="cardhead"><h2>Fleet</h2><span className="muted" style={{ fontSize: '0.85rem' }}>{devices?.length ?? '…'} devices</span></div>
        {devices && devices.length === 0 ? <p className="muted">No devices registered yet.</p> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Device</th><th>Product</th><th>Site</th><th>Data</th><th>Last reading</th><th>Experiment</th></tr></thead>
            <tbody>{(devices || []).map(d => (
              <tr key={d.device_uuid}>
                <td>{EDITION_OF[d.product] ? <a href={`#/${EDITION_OF[d.product]}`}>{d.label || d.device_uuid}</a> : (d.label || d.device_uuid)}
                  <div className="mono muted">{d.device_uuid}</div></td>
                <td>{d.product}</td><td>{d.site || '—'}</td><td><ProvenanceBadge kind={d.provenance} /></td>
                <td title={localTime(d.last_seen, d.timezone)}>{ago(d.last_seen)}</td>
                <td className="mono">{d.experiment_id || '—'}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </div>

      <div className="card">
        <div className="cardhead"><h2>Editions</h2></div>
        <div className="grid2">
          {editions.filter(e => e.id !== 'hq').map(e => (
            <a key={e.id} href={`#/${e.id}`} className="tile" style={{ color: 'inherit', textDecoration: 'none' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <b>{e.name}</b><span className={`badge ${e.status}`}>{e.status}</span>
              </div>
              <div className="muted" style={{ fontSize: '0.85rem', marginTop: 4 }}>{e.tagline}</div>
              {e.status === 'planned' && <div className="t" style={{ marginTop: 6 }}>Needs: {e.needs}</div>}
            </a>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="cardhead"><h2>Experiments</h2></div>
        {experiments.length === 0 ? <p className="muted" style={{ margin: 0 }}>None yet.</p> : (
          <div className="tablewrap"><table>
            <thead><tr><th>Experiment</th><th>Product</th><th>Started</th><th>Data</th></tr></thead>
            <tbody>{experiments.map(x => (
              <tr key={x.id}><td>{x.title}<div className="mono muted">{x.id}</div></td><td>{x.product}</td>
                <td>{localTime(x.started_at)}</td>
                <td><ProvenanceBadge kind={{ hardware: 'measured', simulator: 'simulated', replay: 'replay' }[x.data_origin] || x.data_origin} /></td></tr>))}</tbody>
          </table></div>
        )}
      </div>

      <Catalog />

      <div className="card">
        <div className="cardhead"><h2>Analysis tools</h2><span className="muted" style={{ fontSize: '0.85rem' }}>CoSE browser tools, free</span></div>
        <div className="grid2">
          {TOOLS.map(t => (
            <a key={t.id} className="tile" href={t.url} target="_blank" rel="noreferrer noopener" style={{ color: 'inherit', textDecoration: 'none' }}>
              <b>{t.name} <ExternalLink size={12} aria-hidden /></b>
              <div className="muted" style={{ fontSize: '0.85rem' }}>{t.sub}</div>
            </a>))}
        </div>
      </div>
    </div>
  );
}
