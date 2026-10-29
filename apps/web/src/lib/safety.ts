// What the chat panel will render from a model's reply. The server already builds charts and links itself; these
// checks run again in the browser so a reply can never pull in outside data, open a link, or show an image.

const FORBIDDEN = new Set(['url', 'href', 'loader', 'signals']);

export function unsafeSpecKey(node: unknown, path = ''): string | null {
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i++) {
      const bad = unsafeSpecKey(node[i], `${path}/${i}`);
      if (bad) return bad;
    }
  } else if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      if (FORBIDDEN.has(k)) return `${path}/${k}`;
      const bad = unsafeSpecKey(v, `${path}/${k}`);
      if (bad) return bad;
    }
  }
  return null;
}

// Downloads offered under an answer must be our own export routes.
const EXPORT_HREF = /^\/api\/(datasets|devices)\/[A-Za-z0-9._-]+\/export\?[A-Za-z0-9=&%,._-]*format=(csv|rocrate)[A-Za-z0-9=&%,._-]*$/;
export const safeExportHref = (href: string): string | null => (EXPORT_HREF.test(href) ? href : null);

// Plain paragraphs only: React escapes the text, and nothing in it becomes a link or an image.
export function paragraphs(text: string): string[] {
  return text.split(/\n{2,}/).map(p => p.replace(/[*_`#]+/g, '').trim()).filter(Boolean);
}
