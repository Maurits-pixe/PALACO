import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { securityHeaders } from '../scripts/security-headers.js';

const config = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'));

test('Vercel installs the lockfile and tests before building the static launcher', () => {
  assert.equal(config.installCommand, 'npm ci');
  assert.equal(config.buildCommand, 'npm test && npm run build');
  assert.equal(config.outputDirectory, 'dist');
});

test('Vercel Git deployments keep main disabled without disabling preview branches', () => {
  assert.deepEqual(config.git.deploymentEnabled, { main: false });
});

test('Vercel serves exactly the shared security headers on every launcher path', () => {
  assert.equal(config.headers.length, 1);
  assert.equal(config.headers[0].source, '/(.*)');
  const headers = config.headers[0].headers;
  assert.equal(headers.length, Object.keys(securityHeaders).length);
  assert.deepEqual(
    Object.fromEntries(headers.map(({ key, value }) => [key, value])),
    securityHeaders
  );
});

test('launcher preview requests that crawlers neither index pages nor follow links', () => {
  assert.equal(securityHeaders['X-Robots-Tag'], 'noindex, nofollow');
});
