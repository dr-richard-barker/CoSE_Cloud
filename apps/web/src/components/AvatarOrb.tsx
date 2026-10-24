import { useId } from 'react';

export type AvatarState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'offline';

const LABEL: Record<AvatarState, string> = {
  idle: 'Ready', listening: 'Listening…', thinking: 'Looking at the data…', speaking: 'Speaking…', offline: 'Unavailable',
};

// CoSE_Agent_Avatar, first version: the CoSE orb in the brand navy → blue → teal → mint. It breathes when idle,
// pulses a ring while listening, turns its arcs while thinking and ripples while speaking. With reduced motion the
// state still shows, as a ring colour and the text label, without movement.
export function AvatarOrb({ state, size = 56 }: { state: AvatarState; size?: number }) {
  const id = useId().replace(/:/g, '');
  return (
    <div className={`orb orb-${state}`} style={{ width: size, height: size }} role="img" aria-label={`CoSE_Agent: ${LABEL[state]}`}>
      <style>{ORB_CSS}</style>
      <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden>
        <defs>
          <radialGradient id={`g${id}`} cx="38%" cy="32%" r="75%">
            <stop offset="0" stopColor="#54C9BA" />
            <stop offset=".42" stopColor="#3FB6A8" />
            <stop offset=".78" stopColor="#3B6EA5" />
            <stop offset="1" stopColor="#2F5985" />
          </radialGradient>
        </defs>
        <circle className="ripple r1" cx="50" cy="50" r="34" />
        <circle className="ripple r2" cx="50" cy="50" r="34" />
        <circle className="ring" cx="50" cy="50" r="44" />
        <g className="arcs">
          <path d="M50 10 A40 40 0 0 1 90 50" />
          <path d="M50 90 A40 40 0 0 1 10 50" />
        </g>
        <circle className="core" cx="50" cy="50" r="32" fill={`url(#g${id})`} />
        <ellipse cx="41" cy="38" rx="10" ry="6" fill="#fff" opacity=".28" />
      </svg>
    </div>
  );
}

export const avatarLabel = (s: AvatarState) => LABEL[s];

const ORB_CSS = `
.orb { position: relative; flex-shrink: 0; }
.orb svg { overflow: visible; display: block; }
.orb .ring { fill: none; stroke: var(--line); stroke-width: 3; }
.orb .arcs path { fill: none; stroke: var(--mint); stroke-width: 4; stroke-linecap: round; opacity: 0; }
.orb .ripple { fill: none; stroke: var(--accent2); stroke-width: 2; opacity: 0; }
.orb-listening .ring { stroke: var(--accent2); }
.orb-thinking .arcs path { opacity: .9; }
.orb-speaking .ring { stroke: var(--mint); }
.orb-offline .core { filter: grayscale(1); opacity: .55; }
@media (prefers-reduced-motion: no-preference) {
  .orb-idle .core { animation: orb-breathe 4s ease-in-out infinite; transform-origin: 50px 50px; }
  .orb-listening .ring { animation: orb-pulse 1.1s ease-in-out infinite; transform-origin: 50px 50px; }
  .orb-thinking .arcs { animation: orb-spin 1.4s linear infinite; transform-origin: 50px 50px; }
  .orb-speaking .ripple { animation: orb-ripple 1.6s ease-out infinite; transform-origin: 50px 50px; }
  .orb-speaking .r2 { animation-delay: .8s; }
}
@keyframes orb-breathe { 50% { transform: scale(1.04); } }
@keyframes orb-pulse { 50% { transform: scale(1.08); opacity: .5; } }
@keyframes orb-spin { to { transform: rotate(360deg); } }
@keyframes orb-ripple { 0% { transform: scale(1); opacity: .7; } 100% { transform: scale(1.55); opacity: 0; } }
`;
