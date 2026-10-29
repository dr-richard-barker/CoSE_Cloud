// Browser shims for jsdom. Node-environment test files (// @vitest-environment node) skip them.
if (typeof window !== 'undefined') {
  // jsdom has no matchMedia; the app treats it as "light, wide screen".
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      value: (q: string) => ({ matches: q.includes('min-width'), media: q, addEventListener() {}, removeEventListener() {} }),
    });
  }
  // jsdom does not lay out, so elements have no scrollTo.
  if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {};
}
