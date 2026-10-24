import { Database, FlaskConical, Radio, Rewind } from 'lucide-react';

const META: Record<string, { label: string; title: string; Icon: typeof Database }> = {
  simulated: { label: 'Simulated', title: 'Produced by a software model, not measured on hardware', Icon: FlaskConical },
  measured: { label: 'Measured', title: 'Measured on a CoSE instrument', Icon: Radio },
  replay: { label: 'Replay', title: 'Recorded data replayed from another source', Icon: Rewind },
  catalog: { label: 'Catalog', title: 'Past-experiment catalog (third-party sources)', Icon: Database },
};

export function ProvenanceBadge({ kind }: { kind: string }) {
  const m = META[kind] || { label: kind, title: kind, Icon: Database };
  return (
    <span className={`badge ${kind}`} title={m.title}>
      <m.Icon size={12} aria-hidden /> {m.label}
    </span>
  );
}

export function ProvenanceBadges({ kinds }: { kinds: string[] }) {
  if (!kinds.length) return null;
  return <span style={{ display: 'inline-flex', gap: 6 }}>{kinds.map(k => <ProvenanceBadge key={k} kind={k} />)}</span>;
}
