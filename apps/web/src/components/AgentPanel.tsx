import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, Mic, MicOff, Send, Volume2, X } from 'lucide-react';
import { api, type AgentStatus, type Reply } from '../api';
import { paragraphs, safeExportHref } from '../lib/safety';
import { canListen, canSpeak, listen, speak } from '../lib/speech';
import { AvatarOrb, avatarLabel, type AvatarState } from './AvatarOrb';
import { VegaChart } from './VegaChart';

interface Turn { question: string; reply?: Reply; error?: string }

const SUGGESTIONS: Record<string, string[]> = {
  hq: ['Which devices are reporting right now?', 'What past experiments used Arabidopsis?', 'List our experiments'],
  xseed: ['What was the mean dome temperature yesterday?', 'Chart humidity and VPD over the last 3 days',
    'Any alerts today?'],
};

export function AgentPanel({ edition, open, onClose }: { edition: string; open: boolean; onClose: () => void }) {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [cid, setCid] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [readAloud, setReadAloud] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const stopListening = useRef<() => void>(() => {});
  const stopSpeaking = useRef<() => void>(() => {});
  const log = useRef<HTMLDivElement>(null);
  const micOk = canListen();
  const ttsOk = canSpeak();

  useEffect(() => { api.agentStatus().then(setStatus).catch(() => setStatus(null)); }, []);
  useEffect(() => { setCid(null); setTurns([]); }, [edition]);   // one conversation per edition view
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'smooth' }); }, [turns, busy]);
  useEffect(() => () => { stopListening.current(); stopSpeaking.current(); }, []);

  const state: AvatarState = status && !status.available ? 'offline'
    : listening ? 'listening' : busy ? 'thinking' : speaking ? 'speaking' : 'idle';

  const ask = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setText('');
    setTurns(t => [...t, { question: q }]);
    setBusy(true);
    try {
      const id = cid || (await api.newConversation(edition)).id;
      setCid(id);
      const reply = await api.ask(id, q);
      setTurns(t => t.map((x, i) => (i === t.length - 1 ? { ...x, reply } : x)));
      if (readAloud && reply.speech) {
        stopSpeaking.current = speak(reply.speech, () => setSpeaking(true), () => setSpeaking(false));
      }
    } catch (e) {
      setTurns(t => t.map((x, i) => (i === t.length - 1 ? { ...x, error: String((e as Error).message || e) } : x)));
    } finally {
      setBusy(false);
    }
  }, [busy, cid, edition, readAloud]);

  const toggleMic = () => {
    if (listening) { stopListening.current(); setListening(false); return; }
    setVoiceError(null);
    setListening(true);
    stopListening.current = listen(t => setText(prev => (prev ? `${prev} ${t}` : t)), () => setListening(false),
      e => { setVoiceError(e); setListening(false); });
  };

  return (
    <aside className={`agent${open ? '' : ' closed'}`} aria-label="CoSE_Agent">
      <div className="agenthead">
        <AvatarOrb state={state} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="name">CoSE_Agent</div>
          <div className="state" aria-live="polite">{avatarLabel(state)}{status?.model ? ` · ${status.model}` : ''}</div>
        </div>
        <button className="btn icon" onClick={onClose} aria-label="Close CoSE_Agent"><X size={16} /></button>
      </div>

      <div className="agentlog" ref={log}>
        {status && !status.available && <div className="banner" role="status">{status.reason}</div>}
        {status?.data_notice && <div className="muted" style={{ fontSize: '0.78rem' }}>{status.data_notice}</div>}
        {turns.length === 0 && (
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>Ask about your instruments, their data and past experiments.
              Every number comes from the data, and simulated data is always labelled.</p>
            <div className="suggest">
              {(SUGGESTIONS[edition] || SUGGESTIONS.hq).map(s => (
                <button key={s} className="chip" onClick={() => ask(s)} disabled={busy || status?.available === false}>{s}</button>))}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="stack" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="msg q">{t.question}</div>
            {t.error && <div className="msg a"><span className="err">{t.error}</span></div>}
            {t.reply && <Answer reply={t.reply} />}
          </div>
        ))}
        {busy && <div className="muted" aria-live="polite" style={{ fontSize: '0.85rem' }}>Looking at the data…</div>}
      </div>

      <form className="agentform" onSubmit={e => { e.preventDefault(); ask(text); }}>
        <div className="row">
          <label className="sr-only" htmlFor="agent-q">Question for CoSE_Agent</label>
          <textarea id="agent-q" rows={2} value={text} placeholder="Ask CoSE_Agent…" onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(text); } }}
            disabled={status?.available === false} />
          {micOk && (
            <button type="button" className="btn icon" onClick={toggleMic} aria-pressed={listening}
              aria-label={listening ? 'Stop listening' : 'Speak your question'} disabled={status?.available === false}>
              {listening ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
          )}
          <button type="submit" className="btn primary icon" aria-label="Send" disabled={busy || !text.trim()}><Send size={16} /></button>
        </div>
        <div className="opts">
          {ttsOk ? (
            <label><input type="checkbox" checked={readAloud} onChange={e => { setReadAloud(e.target.checked); if (!e.target.checked) stopSpeaking.current(); }} />
              <Volume2 size={13} aria-hidden /> Read answers aloud</label>
          ) : <span>Read-aloud is not available in this browser</span>}
          {micOk ? <span title="The browser's speech recognition service processes your voice">Voice input: in Chrome, audio goes to Google</span>
            : <span>Voice input is not available in this browser; type instead</span>}
        </div>
        {voiceError && <div className="muted" role="alert" style={{ fontSize: '0.78rem' }}>Voice: {voiceError}</div>}
      </form>
    </aside>
  );
}

function Answer({ reply }: { reply: Reply }) {
  return (
    <div className="msg a">
      {reply.error && <p className="err">{reply.error}</p>}
      {paragraphs(reply.text).map((p, i) => <p key={i}>{p}</p>)}
      {reply.unverified_numbers.length > 0 && (
        <div className="flag">Not found in the data CoSE_Agent read: {reply.unverified_numbers.join(', ')}. Check these.</div>
      )}
      {reply.charts.map(c => <VegaChart key={c.id} spec={c.spec} label="Chart from CoSE_Agent" />)}
      {reply.exports.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          {reply.exports.map(x => {
            const href = safeExportHref(x.href);
            return href ? <a key={x.href} className="btn" href={href} download><Download size={14} /> {x.label}</a> : null;
          })}
        </div>
      )}
      {reply.provenance_footer && <div className="foot">{reply.provenance_footer}</div>}
    </div>
  );
}
