import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';
import { loadLocalTls } from './scripts/local-tls.js';
import { securityHeaders } from './scripts/security-headers.js';

const root = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig(({ command }) => {
  const shared = { plugins: [vue()], worker: { format: 'es' } };
  if (command === 'build') return shared;
  const https = loadLocalTls(root); // Dev and preview fail closed; build needs no local key.
  return {
    ...shared,
    server: { https, host: '127.0.0.1', port: 5173, strictPort: true },
    preview: { https, host: '127.0.0.1', port: 5173, strictPort: true, headers: securityHeaders }
  };
});
