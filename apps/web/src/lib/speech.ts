// Browser speech, feature-detected. Both are optional: text chat always works without them.
// Push-to-talk uses the Web Speech API's recognition; in Chrome that audio is processed by Google's servers, which
// the panel says next to the microphone button. Read-aloud uses speechSynthesis, which runs on the device.

type Recognition = {
  lang: string; interimResults: boolean; continuous: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null;
  start(): void; stop(): void;
};

export function recognitionCtor(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export const canListen = () => recognitionCtor() !== null;
export const canSpeak = () => typeof window !== 'undefined' && 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined';

export function listen(onText: (t: string) => void, onEnd: () => void, onError: (e: string) => void): () => void {
  const Ctor = recognitionCtor();
  if (!Ctor) { onError('voice input is not available in this browser'); return () => {}; }
  const r = new Ctor();
  r.lang = navigator.language || 'en-US';
  r.interimResults = false;
  r.continuous = false;
  r.onresult = e => {
    const parts: string[] = [];
    for (let i = 0; i < e.results.length; i++) parts.push(e.results[i][0].transcript);
    onText(parts.join(' ').trim());
  };
  r.onend = onEnd;
  r.onerror = e => onError(e.error);
  r.start();
  return () => r.stop();
}

export function speak(text: string, onStart: () => void, onEnd: () => void): () => void {
  if (!canSpeak() || !text) { onEnd(); return () => {}; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.onstart = onStart;
  u.onend = onEnd;
  u.onerror = onEnd;
  window.speechSynthesis.speak(u);
  return () => { window.speechSynthesis.cancel(); onEnd(); };
}
