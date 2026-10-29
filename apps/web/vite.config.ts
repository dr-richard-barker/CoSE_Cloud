/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: `npm run dev` proxies /api to a locally running API (uvicorn on 8429). Production: Caddy serves dist/ and
// proxies /api (deploy/compose/Caddyfile), so the app and the API share one origin and the session cookie.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8429' } },
  build: { chunkSizeWarningLimit: 1500 },
  test: { environment: 'jsdom', globals: true, setupFiles: ['src/test/setup.ts'] },
});
