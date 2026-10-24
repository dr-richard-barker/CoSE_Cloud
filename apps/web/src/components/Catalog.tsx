import { useEffect, useState } from 'react';
import { ExternalLink, Film, ImageOff, Search } from 'lucide-react';
import { api, type CatalogItem, type CatalogSource } from '../api';
import { ago } from '../lib/format';

const PAGE = 48;

// Past experiments: metadata and links harvested from the AstroBotany database's sources. Images load from their
// own hosts (Epicollect5, GitHub); CoSE Cloud stores no copies.
export function Catalog() {
  const [sources, setSources] = useState<CatalogSource[]>([]);
  const [species, setSpecies] = useState<{ species: string; n: number }[]>([]);
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [sp, setSp] = useState<string | null>(null);
  const [src, setSrc] = useState<string>('');
  const [media, setMedia] = useState<'image' | ''>('image');
  const [page, setPage] = useState(0);
  const [res, setRes] = useState<{ total: number; items: CatalogItem[] } | null>(null);

  useEffect(() => {
    api.catalogSources().then(setSources).catch(() => {});
    api.catalogSpecies().then(setSpecies).catch(() => {});
  }, []);
  useEffect(() => {
    api.catalogItems({ q: query || undefined, species: sp || undefined, source: src || undefined, media: media || undefined,
      limit: PAGE, offset: page * PAGE })
      .then(setRes).catch(() => setRes({ total: 0, items: [] }));
  }, [query, sp, src, media, page]);

  const harvested = sources.filter(s => s.last_harvest).length;
  return (
    <div className="card">
      <div className="cardhead">
        <div>
          <h2>Past experiments</h2>
          <div className="muted" style={{ fontSize: '0.85rem' }}>
            {sources.reduce((a, s) => a + s.item_count, 0).toLocaleString()} entries from {harvested} of {sources.length} sources
            (Epicollect5 projects and GitHub image collections)
          </div>
        </div>
        <form onSubmit={e => { e.preventDefault(); setPage(0); setQuery(q.trim()); }} style={{ display: 'flex', gap: 6 }}>
          <label className="sr-only" htmlFor="cat-q">Search past experiments</label>
          <input id="cat-q" type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Species, title, notes…" style={{ width: 220 }} />
          <button className="btn icon" aria-label="Search"><Search size={15} /></button>
        </form>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
        <div className="seg" role="group" aria-label="Entries">
          <button aria-pressed={media === 'image'} onClick={() => { setPage(0); setMedia('image'); }}>With images</button>
          <button aria-pressed={media === ''} onClick={() => { setPage(0); setMedia(''); }}>All</button>
        </div>
        <select value={src} onChange={e => { setPage(0); setSrc(e.target.value); }} aria-label="Source" style={{ width: 'auto', maxWidth: 320 }}>
          <option value="">All sources</option>
          {sources.map(s => <option key={s.slug} value={s.slug}>{s.title} ({s.item_count})</option>)}
        </select>
        <div className="chips" role="group" aria-label="Species">
          {species.slice(0, 8).map(s => (
            <button key={s.species} className="chip" aria-pressed={sp === s.species}
              onClick={() => { setPage(0); setSp(sp === s.species ? null : s.species); }}>{s.species} · {s.n}</button>))}
        </div>
      </div>
      {sources.length > 0 && harvested === 0 && (
        <p className="muted">Nothing harvested yet: run <span className="mono">cose-cloud-catalog</span>.</p>)}
      {res && (
        <>
          <div className="thumbs">
            {res.items.map(it => (
              <a key={it.id} className="thumb" href={it.media_url || '#'} target="_blank" rel="noreferrer noopener"
                title={`${it.title} — ${it.source_title}`}>
                <div className="img">
                  {it.media_kind === 'image' && it.thumb_url
                    ? <img src={it.thumb_url} alt={it.title} loading="lazy" referrerPolicy="no-referrer" />
                    : it.media_kind === 'video' ? <Film size={22} aria-hidden /> : <ImageOff size={22} aria-hidden />}
                </div>
                <div className="cap"><b>{it.title}</b><span className="muted">{it.species || it.source_title}</span></div>
              </a>
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10, fontSize: '0.85rem' }}>
            <span className="muted">{res.total.toLocaleString()} matches</span>
            <span style={{ display: 'flex', gap: 6 }}>
              <button className="btn" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Previous</button>
              <button className="btn" disabled={(page + 1) * PAGE >= res.total} onClick={() => setPage(p => p + 1)}>Next</button>
            </span>
          </div>
        </>
      )}
      <details style={{ marginTop: 10 }}>
        <summary className="muted" style={{ cursor: 'pointer', fontSize: '0.85rem' }}>Sources and harvest status</summary>
        <div className="tablewrap"><table>
          <thead><tr><th>Source</th><th>Kind</th><th>Entries</th><th>Harvested</th></tr></thead>
          <tbody>{sources.map(s => (
            <tr key={s.slug}>
              <td>{s.url ? <a href={s.url} target="_blank" rel="noreferrer noopener">{s.title} <ExternalLink size={11} /></a> : s.title}
                {s.last_error && <div className="muted" style={{ fontSize: '0.75rem' }}>last error: {s.last_error.slice(0, 120)}</div>}</td>
              <td className="mono">{s.kind}</td><td>{s.item_count}</td><td>{ago(s.last_harvest)}</td>
            </tr>))}</tbody>
        </table></div>
      </details>
    </div>
  );
}
