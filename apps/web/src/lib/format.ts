export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return 'never';
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 90) return `${s} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export function localTime(iso: string | null, tz?: string): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, { timeZone: tz, month: 'short', day: 'numeric', hour: '2-digit',
    minute: '2-digit', timeZoneName: 'short' });
}

export function num(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined) return '—';
  const digits = unit === 'flag' ? 0 : Math.abs(v) >= 100 ? 0 : unit === 'kPa' || unit === '1' ? 2 : 1;
  return v.toFixed(digits);
}
