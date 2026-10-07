import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { execFileSync } from 'node:child_process';
import { X509Certificate } from 'node:crypto';
import { createReport, root } from './report.mjs';
import { temporarySubject, certificates, request, viteProcess, waitForHttps, expectedExit } from './local-fixtures.mjs';

const report = createReport('tls', import.meta.url, [
  'Actual Vite dev/preview/build executed using temporary copies of the bound source.',
  'TLS fixture CA is disposable and supplied only to individual Node clients; no system/browser trust store changes or mkcert execution.',
  'No hosted Site, real external app origin, production deployment or CI was tested.'
]);
const directory = temporarySubject('tls');
try {
  await report.check('CONFIG-MISSING-CERT-DEV', async () => {
    const outcome = await expectedExit(viteProcess(directory));
    assert.equal(outcome.code, 1); assert.match(outcome.log, /Lokale HTTPS-certificaten ontbreken/); return outcome;
  }, 'actual Vite dev CLI, no certificates');
  await report.check('CONFIG-MISSING-CERT-PREVIEW', async () => {
    const outcome = await expectedExit(viteProcess(directory, true));
    assert.equal(outcome.code, 1); assert.match(outcome.log, /Lokale HTTPS-certificaten ontbreken/); return outcome;
  }, 'actual Vite preview CLI, no certificates');
  await report.check('BUILD-WITHOUT-LOCAL-CERTS', async () => {
    const output = execFileSync(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'), 'build', '--configLoader', 'native'], { cwd: directory, timeout: 30000, encoding: 'utf8' });
    assert.ok(fs.existsSync(path.join(directory, 'dist/index.html'))); return { output, certificatesPresent: false };
  }, 'actual SFC + worker production build');
  const tls = certificates(directory);
  const publicCaFile = 'tls-fixture-ca-public.pem';
  fs.writeFileSync(path.join(root, 'evidence', publicCaFile), tls.ca);
  await report.check('CONFIG-INVALID-KEY-CERT', async () => {
    fs.writeFileSync(path.join(directory, 'certs/localhost-key.pem'), 'not a key');
    try {
      const outcome = await expectedExit(viteProcess(directory));
      assert.equal(outcome.code, 1); assert.match(outcome.log, /key\/certificaatcombinatie is ongeldig/); return outcome;
    } finally { fs.writeFileSync(path.join(directory, 'certs/localhost-key.pem'), tls.key, { mode: 0o600 }); }
  }, 'actual Vite config + TLS secure-context validation');
  for (const preview of [false, true]) await report.check(preview ? 'HTTPS-PREVIEW-AND-NO-HTTP-FALLBACK' : 'HTTPS-DEV-AND-NO-HTTP-FALLBACK', async () => {
    const process = viteProcess(directory, preview);
    try {
      const response = await waitForHttps(process, tls.ca); assert.equal(response.status, 200);
      assert.match(response.body, /PALACO Hoofdkantoor/);
      await assert.rejects(request('http://127.0.0.1:5173'));
      await assert.rejects(request('https://127.0.0.1:5173'));
      return { status: response.status, plainHttpAccepted: false, untrustedCaAccepted: false, log: process.log() };
    } finally { await process.stop(); }
  }, 'real local HTTPS request with explicit CA verification + rejected HTTP and untrusted client');
  await report.check('STRICT-PORT-CONFLICT', async () => {
    const blocker = net.createServer();
    await new Promise((resolve, reject) => { blocker.once('error', reject); blocker.listen(5173, '127.0.0.1', resolve); });
    try {
      const outcome = await expectedExit(viteProcess(directory));
      assert.equal(outcome.code, 1); assert.match(outcome.log, /5173.*already in use/); return outcome;
    } finally { await new Promise(resolve => blocker.close(resolve)); }
  }, 'real occupied TCP port and actual Vite dev CLI');
  report.finish({ openssl: execFileSync('openssl', ['version'], { encoding: 'utf8' }).trim(),
    fixtureCaFingerprint256: new X509Certificate(tls.ca).fingerprint256, publicCaFile });
} finally { fs.rmSync(directory, { recursive: true, force: true }); }
