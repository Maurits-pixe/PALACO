import fs from 'node:fs';
import { securityHeaders } from './security-headers.js';
fs.mkdirSync(new URL('../public/', import.meta.url), { recursive: true });
fs.writeFileSync(new URL('../public/_headers', import.meta.url), '/*\n' + Object.entries(securityHeaders).map(([name, value]) => `  ${name}: ${value}`).join('\n') + '\n');
