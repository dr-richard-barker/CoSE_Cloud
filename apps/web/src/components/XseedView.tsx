import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Download, RefreshCw } from 'lucide-react';
import { api, type AlertEvent, type ChartOut, type Device, type Edition, type Reading } from '../api';
import { ago, localTime, num } from '../lib/format';
import { ProvenanceBadge } from './ProvenanceBadge';
import { VegaChart } from './VegaChart';

type Range = '24h' | '3d' | 'crop';
const RANGE_H: Record<Exclude<Range, 'crop'>, number> = { '24h': 24, '3d': 72 };
const CLIMATE = ['sensors.dome_temp_c', 'sensors.root_temp_c', 'sensors.dome_humidity_pct', 'sensors.vpd_kpa'];
const CANOPY = ['biometrics_3d.canopy_height_avg_mm', 'biometrics_3d.canopy_height_max_mm'];
const POLL_MS = 5000;

type Row = { ts: string; series: string; short: string; value: number | null };

export function XseedView({ edition }: { edition: Edition }) {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [uuid, setUuid] = useState<string | null>(null);
  const [range, setRange] = useState<Range>('24h');
  const [climate, setClimate] = useState<ChartOut | null>(null);
  const [canopy, setCanopy] = useState<ChartOut | null>(null);
  const [latest, setLatest] = useState<Reading[]>([]);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [live, setLive] = useState<{ climate: Row[]; canopy: Row[] }>({ climate: [], canopy: [] });
  const [lastTs, setLastTs] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.devices('xseed').then(d => { setDevices(d); setUuid(u => u || d[0]?.device_uuid || null); })
      .catch(e => setError(String(e.message || e)));
  }, []);
  const device = useMemo(() => devices?.find(d => d.device_uuid === uuid) || null, [devices, uuid]);
  const keyMetrics = edition.key_metrics || CLIMATE;

  const win = useMemo(() => {
    if (!device) return null;
    const end = new Date();
    const start = range === 'crop' && device.first_seen ? new Date(device.first_seen)
      : new Date(end.getTime() - RANGE_H[range === 'crop' ? '3d' : range] * 3600e3);
    return { start: start.toISOString() };
  }, [device, range]);

  const load = useCallback(() => {
    if (!device || !win) return;
    setError(null);
    setLive({ climate: [], canopy: [] });
    Promise.all([
      api.chart(device.device_uuid, CLIMATE, win, 'Climate'),
      api.chart(device.device_uuid, CANOPY, win, 'Canopy (ToF)'),
      api.latest(device.device_uuid, [...new Set([...keyMetrics, 'growth_day'])]),
      api.alerts(device.device_uuid, { day: 'today' }),
    ]).then(([c1, c2, l, a]) => {
      setClimate(c1); setCanopy(c2); setLatest(l.readings); setAlerts(a.events);
      setLastTs(l.readings.reduce<string | null>((m, r) => (!m || r.ts > m ? r.ts : m), null));
    }).catch(e => setError(String(e.message || e)));
  }, [device, win, keyMetrics]);
  useEffect(load, [load]);

  // Live: new readings since the last one seen are pushed into both charts and the tiles.
  useEffect(() => {
    if (!device || !lastTs || !climate || !canopy) return;
    let after = lastTs;
    const timer = window.setInterval(async () => {
      try {
        const { rows } = await api.since(device.device_uuid, [...new Set([...CLIMATE, ...CANOPY, ...keyMetrics, 'growth_day'])], after);
        if (!rows.length) return;
        after = rows[rows.length - 1].ts;
        setLastTs(after);
        const toRows = (spec: ChartOut) => rows.flatMap(r => {
          const s = spec.spec.usermeta?.series_by_metric?.[r.metric];
          return s ? [{ ts: r.ts, series: s.series, short: s.short, value: r.value }] : [];
        });
        setLive(prev => ({ climate: [...prev.climate, ...toRows(climate)], canopy: [...prev.canopy, ...toRows(canopy)] }));
        setLatest(prev => prev.map(p => {
          const newest = [...rows].reverse().find(r => r.metric === p.metric);
          return newest ? { ...p, ts: newest.ts, value: newest.value, quality: newest.quality } : p;
        }));
      } catch { /* next tick */ }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [device, climate, canopy, keyMetrics, lastTs === null]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <div className="banner" role="alert"><AlertTriangle size={16} />{error}</div>;
  if (!devices) return <p className="muted">Loading…</p>;
  if (!device) return <div className="card"><h2>No XSeed devices yet</h2>
    <p className="muted">Register one, or run the simulator: <span className="mono">cose-cloud-sim backfill</span>.</p></div>;

  const tiles = keyMetrics.map(k => latest.find(r => r.metric === k)).filter(Boolean) as Reading[];
  const day = latest.find(r => r.metric === 'growth_day');
  const exportWin = win || {};
  return (
    <div className="stack">
      <div className="pagehead">
        <div>
          <h1>{edition.name}</h1>
          <p>{edition.tagline}</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {devices.length > 1 && (
            <select value={uuid || ''} onChange={e => setUuid(e.target.value)} aria-label="Device" style={{ width: 'auto' }}>
              {devices.map(d => <option key={d.device_uuid} value={d.device_uuid}>{d.label || d.device_uuid}</option>)}
            </select>
          )}
          <div className="seg" role="group" aria-label="Time range">
            {(['24h', '3d', 'crop'] as Range[]).map(r => (
              <button key={r} aria-pressed={range === r} onClick={() => setRange(r)}>{r === 'crop' ? 'Whole crop' : r}</button>))}
          </div>
          <button className="btn icon" onClick={load} aria-label="Reload"><RefreshCw size={15} /></button>
        </div>
      </div>

      {device.provenance === 'simulated' && (
        <div className="banner" role="note"><AlertTriangle size={16} />
          <div><b>Simulated data.</b> {edition.data_note} <span className="muted">{device.provenance_note}</span></div></div>
      )}

      <div className="card">
        <div className="cardhead">
          <div>
            <h2>{device.label || device.device_uuid} <span className="mono muted">{device.device_uuid}</span></h2>
            <div className="muted" style={{ fontSize: '0.85rem' }}>
              {device.site} · {device.timezone} · experiment <span className="mono">{device.experiment_id || '—'}</span>
              {day?.value != null && <> · growth day {day.value.toFixed(1)}</>}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <ProvenanceBadge kind={device.provenance} />
            <span className="muted" style={{ fontSize: '0.8rem' }}><span className="livedot" /> live · last reading {ago(lastTs)}</span>
          </div>
        </div>
        <div className="tiles">
          {tiles.map(t => (
            <div className="tile" key={t.metric}>
              <div className="k">{t.label}</div>
              <div className="v">{num(t.value, t.unit)}<small>{t.unit}</small></div>
              <div className="t">{t.quality !== 'ok' ? t.quality.replace('_', ' ') : localTime(t.ts, device.timezone)}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid2">
        {climate && <VegaChart spec={climate.spec} liveRows={live.climate} label="Climate chart" />}
        {canopy && <VegaChart spec={canopy.spec} liveRows={live.canopy} label="Canopy chart" />}
      </div>

      <div className="grid2">
        <div className="card">
          <div className="cardhead"><h2>Alerts today</h2><ProvenanceBadge kind={device.provenance} /></div>
          {alerts.length === 0 ? <p className="muted" style={{ margin: 0 }}>None.</p> : (
            <div className="tablewrap"><table>
              <thead><tr><th>Time</th><th>Alert</th><th>Event</th></tr></thead>
              <tbody>{alerts.map((a, i) => <tr key={i}><td>{localTime(a.ts, device.timezone)}</td><td className="mono">{a.alert}</td><td>{a.event.replace(/_/g, ' ')}</td></tr>)}</tbody>
            </table></div>
          )}
        </div>
        <div className="card">
          <div className="cardhead"><h2>Export</h2></div>
          <p className="muted" style={{ marginTop: 0, fontSize: '0.88rem' }}>The selected range, all climate and canopy metrics.
            Every row carries its provenance; simulated files end in <span className="mono">_SIMULATED</span>.</p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <a className="btn" href={api.exportHref(device.device_uuid, [...CLIMATE, ...CANOPY], 'csv', exportWin)} download><Download size={14} /> CSV</a>
            <a className="btn" href={api.exportHref(device.device_uuid, [...CLIMATE, ...CANOPY], 'rocrate', exportWin)} download><Download size={14} /> RO-Crate 1.1</a>
          </div>
        </div>
      </div>
    </div>
  );
}
