import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { root } from './report.mjs';
import { certificates, request, temporarySubject, viteProcess } from './local-fixtures.mjs';

const runtimeConfig = process.env.PALACO_BROWSER_RUNTIME_CONFIG
  ? JSON.parse(fs.readFileSync(process.env.PALACO_BROWSER_RUNTIME_CONFIG, 'utf8')) : {};
const dangerous = ['--disable-web-security', '--allow-running-insecure-content', '--ignore-certificate-errors'];
if ((runtimeConfig.args || []).some(arg => dangerous.some(flag => arg === flag || arg.startsWith(`${flag}=`)))) {
  throw new Error('Browser harness rejects disabled web security, mixed-content or global certificate bypass flags.');
}
const launcherDirectory = temporarySubject('5criptie-integration-launcher');
const launcherTls = certificates(launcherDirectory);
const moduleSource = path.resolve(root, '../5criptie-preview');
const moduleDirectory = fs.mkdtempSync(path.join(path.join(root, '.test-tmp'), '5criptie-integration-module-'));
for (const name of ['package.json', 'vite.config.js', 'index.html', 'src', 'scripts', 'public']) {
  fs.cpSync(path.join(moduleSource, name), path.join(moduleDirectory, name), { recursive: true });
}
fs.mkdirSync(path.join(moduleDirectory, 'certs'));
fs.writeFileSync(path.join(moduleDirectory, 'certs', 'localhost-key.pem'), launcherTls.key, { mode: 0o600 });
fs.writeFileSync(path.join(moduleDirectory, 'certs', 'localhost.pem'), launcherTls.cert);

let launcher;
let scriptie;
let browser;
try {
  launcher = viteProcess(launcherDirectory, true);
  scriptie = viteProcess(moduleDirectory);

  const deadline = performance.now() + 10000;
  let manifestResponse;
  while (performance.now() < deadline) {
    if (launcher.child.exitCode !== null) throw new Error(`Launcher preview exited: ${launcher.log()}`);
    if (scriptie.child.exitCode !== null) throw new Error(`5CRIPTIE preview exited: ${scriptie.log()}`);
    try {
      manifestResponse = await request('https://127.0.0.1:5176/.well-known/palaco-app.json', { ca: launcherTls.ca });
      if (manifestResponse.status === 200) break;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(manifestResponse?.status, 200, `5CRIPTIE HTTPS preview did not become ready: ${scriptie.log()}`);
  assert.deepEqual(JSON.parse(manifestResponse.body), {
    appId: '5criptie',
    version: '1.0.0-preview.1',
    status: 'preview-only'
  });

  browser = await chromium.launch({
    headless: true,
    ...(runtimeConfig.executablePath ? { executablePath: runtimeConfig.executablePath } : {}),
    args: runtimeConfig.args || []
  });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await page.goto('https://127.0.0.1:5173');
  const card = page.locator('[data-module="5criptie"]');
  await card.locator('input').fill('https://localhost:5176');
  await card.locator('[data-verify]').click();
  await card.locator('[data-status]').filter({ hasText: 'Modulemetadata bevestigd' }).waitFor();
  assert.equal(await card.locator('[data-launch]').isEnabled(), true);

  const [popup] = await Promise.all([
    page.waitForEvent('popup'),
    card.locator('[data-launch]').click()
  ]);
  await popup.getByRole('heading', { name: 'Signal overview' }).waitFor();
  assert.equal(new URL(popup.url()).origin, 'https://localhost:5176');
  await popup.getByText('Geen echte monitoring.').waitFor();
  await popup.getByText('Alle data is synthetisch · Geen sensoren · Geen scans · Geen acties').waitFor();
  const documentOrigin = new URL(popup.url()).origin;
  const remoteRequests = [];
  popup.on('request', request => {
    if (new URL(request.url()).origin !== documentOrigin) remoteRequests.push(request.url());
  });
  await popup.reload();
  await popup.getByRole('heading', { name: 'Signal overview' }).waitFor();
  assert.deepEqual(remoteRequests, []);
  await context.close();
  console.log('PASS: NEO verified and opened the real local 5CRIPTIE HTTPS preview; dashboard content remained synthetic.');
} finally {
  await browser?.close();
  await scriptie?.stop();
  await launcher?.stop();
  fs.rmSync(launcherDirectory, { recursive: true, force: true });
  fs.rmSync(moduleDirectory, { recursive: true, force: true });
}
