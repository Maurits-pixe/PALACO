import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../', import.meta.url));
const dist = path.join(root, 'dist');
const browserPath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
  ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome']
    .find(candidate => fs.existsSync(candidate));
const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
  const requested = pathname === '/' ? 'index.html' : decodeURIComponent(pathname.slice(1));
  const file = path.resolve(dist, requested);
  if (!file.startsWith(`${dist}${path.sep}`) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    response.writeHead(404).end();
    return;
  }
  const extension = path.extname(file);
  const contentType = extension === '.html' ? 'text/html; charset=utf-8'
    : extension === '.js' ? 'text/javascript; charset=utf-8'
      : extension === '.css' ? 'text/css; charset=utf-8'
        : 'application/octet-stream';
  response.writeHead(200, { 'Content-Type': contentType, 'Cache-Control': 'no-store' });
  fs.createReadStream(file).pipe(response);
});

if (!browserPath && !process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
  throw new Error('Chromium ontbreekt. Installeer `npx playwright install chromium` of stel PLAYWRIGHT_CHROMIUM_EXECUTABLE in.');
}

await new Promise((resolve, reject) => {
  server.once('error', reject);
  server.listen(0, '127.0.0.1', resolve);
});

let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(browserPath ? { executablePath: browserPath } : {}),
    args: ['--no-sandbox']
  });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const browserErrors = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  const address = server.address();
  await page.goto(`http://127.0.0.1:${address.port}/`);
  await page.getByText('LOKAAL BESCHIKBAAR').waitFor();

  const passphrase = 'unieke aether browser testzin';
  const originalName = 'geheim-fixture.txt';
  const originalContent = 'AETHER houdt deze voorbeelddata versleuteld.';
  await page.locator('#file-to-encrypt').setInputFiles({
    name: originalName,
    mimeType: 'text/plain',
    buffer: Buffer.from(originalContent)
  });
  await page.locator('#passphrase').fill(passphrase);
  await page.locator('#confirm-passphrase').fill('andere wachtzin voor test');
  await page.getByRole('button', { name: 'VERSLEUTEL EN BEWAAR LOKAAL' }).click();
  await page.getByRole('alert').filter({ hasText: 'wachtzinnen komen niet overeen' }).waitFor();
  assert.equal(await page.locator('.vault-list li').count(), 0);
  await page.locator('#confirm-passphrase').fill(passphrase);
  await page.getByRole('button', { name: 'VERSLEUTEL EN BEWAAR LOKAAL' }).click();
  await page.getByRole('status').filter({ hasText: 'Bestand versleuteld en lokaal opgeslagen' }).waitFor();
  assert.equal(await page.locator('.vault-list li').count(), 1);

  const storedItems = await page.evaluate(async () => {
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open('palaco-aether-vault', 1);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const items = await new Promise((resolve, reject) => {
      const request = database.transaction('encrypted-files').objectStore('encrypted-files').getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    database.close();
    return items;
  });
  assert.equal(storedItems.length, 1);
  const persisted = JSON.stringify(storedItems[0]);
  assert.ok(!persisted.includes(passphrase));
  assert.ok(!persisted.includes(originalName));

  const [backup] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'BACK-UP', exact: true }).click()
  ]);
  const backupPath = await backup.path();
  const backupContents = await fs.promises.readFile(backupPath, 'utf8');
  assert.ok(!backupContents.includes(passphrase));
  assert.ok(!backupContents.includes(originalName));

  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: /^Verwijder item/ }).click();
  await page.locator('.vault-list').waitFor({ state: 'detached' });
  await page.locator('.backup-import input').setInputFiles({
    name: backup.suggestedFilename(),
    mimeType: 'application/json',
    buffer: Buffer.from(backupContents)
  });
  await page.getByRole('status').filter({ hasText: 'Versleutelde back-up geïmporteerd' }).waitFor();
  assert.equal(await page.locator('.vault-list li').count(), 1);
  await page.locator('.backup-import input').setInputFiles({
    name: 'ongeldige-backup.json',
    mimeType: 'application/json',
    buffer: Buffer.from('{"schema":"unknown"}')
  });
  await page.getByRole('alert').filter({ hasText: 'Onbekend of ongeldig' }).waitFor();
  assert.equal(await page.locator('.vault-list li').count(), 1);

  await page.locator('#vault-passphrase').fill('onjuiste wachtzin testwaarde');
  await page.getByRole('button', { name: 'ONTGRENDEL' }).click();
  await page.getByRole('alert').filter({ hasText: 'Ontsleutelen' }).waitFor();
  assert.equal(await page.locator('.vault-list li').count(), 1);

  await page.locator('#vault-passphrase').fill(passphrase);
  const [restored] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'ONTGRENDEL' }).click()
  ]);
  assert.equal(restored.suggestedFilename(), originalName);
  const restoredPath = await restored.path();
  assert.equal(await fs.promises.readFile(restoredPath, 'utf8'), originalContent);
  await page.locator('#passphrase').fill(passphrase);
  await page.locator('#confirm-passphrase').fill(passphrase);
  await page.locator('#vault-passphrase').fill(passphrase);
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForFunction(() => [...document.querySelectorAll('input[type="password"]')]
    .every(input => input.value === ''));
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  });
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'WIS KLUIS' }).click();
  assert.equal(await page.locator('.vault-list li').count(), 1);
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'WIS KLUIS' }).click();
  await page.locator('.vault-list').waitFor({ state: 'detached' });
  await page.getByText('Nog geen versleutelde bestanden in deze browser.').waitFor();
  assert.equal(await page.locator('.vault-list li').count(), 0);
  assert.deepEqual(browserErrors, []);
  await context.close();
  console.log(JSON.stringify({
    identity: 'aether',
    browser: 'chromium',
    encryptedPersistence: 'ciphertext-only',
    backup: 'export-import-roundtrip',
    decryption: 'wrong-passphrase-rejected-and-correct-passphrase-restored-original'
  }));
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
