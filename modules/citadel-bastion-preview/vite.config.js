import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
import { securityHeaders } from './scripts/security-headers.js';

const root = fileURLToPath(new URL('.', import.meta.url));
export default defineConfig(({ command }) => {
  const shared = { plugins: [vue()] };
  if (command === 'build') return shared;
  const keyPath = path.join(root, 'certs', 'localhost-key.pem');
  const certPath = path.join(root, 'certs', 'localhost.pem');
  if (!fs.existsSync(keyPath) || !fs.existsSync(certPath)) throw new Error('Lokale HTTPS-certificaten ontbreken.');
  const https = { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) };
  return { ...shared, server: { https, host: '127.0.0.1', port: 5175, strictPort: true, headers: securityHeaders }, preview: { https, host: '127.0.0.1', port: 5175, strictPort: true, headers: securityHeaders } };
});
