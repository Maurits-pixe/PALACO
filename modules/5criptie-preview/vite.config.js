import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';
import { loadLocalTls } from './scripts/local-tls.js';
import { securityHeaders } from './scripts/security-headers.js';

const root = fileURLToPath(new URL('.', import.meta.url));
const launcherOrigins = ['https://localhost:5173', 'https://127.0.0.1:5173'];

export default defineConfig(({ command }) => {
  const shared = { plugins: [vue()] };
  if (command === 'build') return shared;
  const https = loadLocalTls(root);
  return {
    ...shared,
    server: {
      https,
      host: '127.0.0.1',
      port: 5176,
      strictPort: true,
      cors: { origin: launcherOrigins },
      headers: securityHeaders
    },
    preview: {
      https,
      host: '127.0.0.1',
      port: 5176,
      strictPort: true,
      cors: { origin: launcherOrigins },
      headers: securityHeaders
    }
  };
});
