import fs from 'node:fs';
import { securityHeaders } from './security-headers.js';

fs.mkdirSync(new URL('../public/', import.meta.url), { recursive: true });
fs.writeFileSync(
  new URL('../public/_headers', import.meta.url),
  '/.well-known/palaco-app.json\n  Access-Control-Allow-Origin: https://127.0.0.1:5173\n/*\n' +
    Object.entries(securityHeaders).map(([name, value]) => `  ${name}: ${value}`).join('\n') +
    '\n'
);
