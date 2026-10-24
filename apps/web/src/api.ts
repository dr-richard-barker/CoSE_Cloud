// Typed client for the CoSE Cloud API (services/src/cose_cloud/api.py). Same origin, session cookie.

export type Provenance = 'measured' | 'simulated' | 'replay';

export interface Edition {
  id: string; name: string; tagline: string; status: 'live' | 'planned'; products: string[]; panels: string[];
  agent_tools: 'all' | string[]; key_metrics?: string[]; data_note?: string; data_source?: string; needs?: string;
}
export interface Me {
  user: { id: number; email: string; name: string | null; role: string };
  org: { id: number; slug: string; name: string };
  entitlements: { tier: string; llm_mode: 'hosted' | 'local' | 'off' };
}
export interface Device {
  device_uuid: string; product: string; variant: string | null; label: string | null; data_origin: string;
  first_seen: string | null; last_seen: string | null; site: string | null; timezone: string;
  experiment_id: string | null; provenance: Provenance; provenance_note: string | null;
}
export interface Reading { metric: string; ts: string; value: number | null; quality: string; label: string; unit: string }
export interface Experiment { id: string; product: string; device_uuid: string | null; title: string; crop: string | null;
  started_at: string; ended_at: string | null; data_origin: string }
export interface AlertEvent { ts: string; alert: string; event: string }
export interface CatalogSource { id: number; kind: string; slug: string; title: string; url: string | null;
  last_harvest: string | null; last_error: string | null; item_count: number; provenance: Record<string, string> }
export interface CatalogItem { id: number; title: string; species: string | null; captured_at: string | null;
  uploaded_at: string | null; fields: { name: string; value: string }[]; media_url: string | null; thumb_url: string | null;
  media_kind: string | null; source: string; source_title: string; source_kind: string }
export interface VegaSpec { [key: string]: unknown; usermeta?: { provenance?: string[]; notes?: string[];
  series_by_metric?: Record<string, { series: string; short: string }> } }
export interface ChartOut { spec: VegaSpec; window: string; bucket_s: number; window_utc: [string, string] }
export interface ExportLink { dataset_id: string; format: string; href: string; label: string }
export interface Reply {
  text: string; error: string | null; speech: string; charts: { id: string; spec: VegaSpec }[]; exports: ExportLink[];
  provenance: string[]; provenance_footer: string | null; unverified_numbers: string[]; model: string; provider: string;
}
export interface AgentStatus { llm_mode: string; model: string | null; available: boolean; reason: string | null;
  month_spend_usd: number; monthly_cap_usd: number | null; data_notice: string | null }

export class AuthError extends Error {}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: 'same-origin', ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  if (r.status === 401) throw new AuthError('sign in');
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return r.json() as Promise<T>;
}

const qs = (p: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => [k, String(v)])).toString();

export const api = {
  login: (email: string, password: string) => j<{ ok: boolean }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => j<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  me: () => j<Me>('/api/me'),
  editions: () => j<Edition[]>('/api/editions'),
  devices: (product?: string) => j<Device[]>(`/api/devices?${qs({ product })}`),
  latest: (uuid: string, metrics?: string[]) => j<{ readings: Reading[] }>(`/api/devices/${encodeURIComponent(uuid)}/latest?${qs({ metrics: metrics?.join(',') })}`),
  chart: (uuid: string, metrics: string[], win: { day?: string; start?: string; end?: string }, title = '') =>
    j<ChartOut>(`/api/devices/${encodeURIComponent(uuid)}/chart?${qs({ metrics: metrics.join(','), title, ...win })}`),
  since: (uuid: string, metrics: string[], after: string) =>
    j<{ rows: { metric: string; ts: string; value: number | null; quality: string }[]; server_time: string }>(
      `/api/devices/${encodeURIComponent(uuid)}/since?${qs({ metrics: metrics.join(','), after })}`),
  alerts: (uuid: string, win: { day?: string; start?: string; end?: string }) =>
    j<{ window: string; events: AlertEvent[] }>(`/api/devices/${encodeURIComponent(uuid)}/alerts?${qs(win)}`),
  experiments: () => j<Experiment[]>('/api/experiments'),
  catalogSources: () => j<CatalogSource[]>('/api/catalog/sources'),
  catalogItems: (p: { q?: string; species?: string; source?: string; media?: string; limit?: number; offset?: number }) =>
    j<{ total: number; items: CatalogItem[] }>(`/api/catalog/items?${qs(p)}`),
  catalogSpecies: () => j<{ species: string; n: number }[]>('/api/catalog/species'),
  exportHref: (uuid: string, metrics: string[], format: 'csv' | 'rocrate', win: { start?: string; end?: string; day?: string }) =>
    `/api/devices/${encodeURIComponent(uuid)}/export?${qs({ metrics: metrics.join(','), format, ...win })}`,
  agentStatus: () => j<AgentStatus>('/api/agent/status'),
  newConversation: (edition: string) => j<{ id: string }>('/api/agent/conversations', { method: 'POST', body: JSON.stringify({ edition }) }),
  ask: (cid: string, question: string) => j<Reply>(`/api/agent/conversations/${cid}/ask`, { method: 'POST', body: JSON.stringify({ question }) }),
};
