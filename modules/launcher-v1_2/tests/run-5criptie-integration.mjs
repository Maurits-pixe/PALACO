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
  const reviewState = await popup.locator('.review-panel').evaluate(panel => ({
    total: panel.querySelector('.review-total strong').textContent,
    rows: [...panel.querySelectorAll('.review-row')].map(row => ({
      severity: row.querySelector('.review-label').textContent.trim(),
      count: row.querySelector('strong').textContent.trim(),
      percent: row.querySelector('.review-percent').textContent.trim(),
      width: row.querySelector('.review-track i').style.width
    }))
  }));
  assert.equal(reviewState.total, '03');
  assert.equal(await popup.locator('.review-total').getAttribute('aria-label'), '3 reviewmeldingen');
  assert.equal(await popup.locator('.review-empty').count(), 0);
  assert.equal(await popup.locator('.review-breakdown').getAttribute('aria-hidden'), 'true');
  assert.equal((await popup.locator('.review-panel [role="status"]').textContent()).trim(),
    'Hoog: 2 reviewmeldingen, 67%. Middel: 1 reviewmelding, 33%. Laag: 0 reviewmeldingen, 0%');
  assert.deepEqual(reviewState.rows.map(({ severity, count, percent }) => ({ severity, count, percent })), [
    { severity: 'Hoog', count: '02', percent: '67%' },
    { severity: 'Middel', count: '01', percent: '33%' },
    { severity: 'Laag', count: '00', percent: '0%' }
  ]);
  assert.equal(reviewState.rows[0].width, '67%');
  assert.equal(reviewState.rows[1].width, '33%');
  assert.equal(reviewState.rows[2].width, '0%');
  const reviewDetails = popup.locator('.review-details');
  assert.equal(await reviewDetails.locator('summary').textContent(), 'Toon reviewverdeling als tabel');
  assert.equal(await reviewDetails.locator('table').isVisible(), false);
  await reviewDetails.locator('summary').focus();
  await popup.keyboard.press('Enter');
  assert.equal(await reviewDetails.locator('table').isVisible(), true);
  assert.deepEqual((await reviewDetails.locator('table tbody tr').evaluateAll(rows =>
    rows.map(row => [...row.querySelectorAll('th, td')].map(cell => cell.textContent.trim())))), [
    ['Hoog', '2', '67%'],
    ['Middel', '1', '33%'],
    ['Laag', '0', '0%'],
    ['Totaal', '3', '100%']
  ]);
  await popup.keyboard.press('Space');
  assert.equal(await reviewDetails.locator('table').isVisible(), false);
  const eventRows = popup.locator('.events-panel tbody tr');
  await popup.evaluate(() => {
    window.print = () => {
      window.__reviewTableWasOpenForPrint = document.querySelector('.review-details').open;
      window.__filterStatusAtPrint = document.querySelector('.events-panel [role="status"]').textContent.trim();
      window.__fixtureRowsAtPrint = document.querySelectorAll('.events-panel tbody tr').length;
      window.dispatchEvent(new Event('afterprint'));
    };
  });
  await popup.getByRole('button', { name: 'Hoog', exact: true }).click();
  assert.equal(await eventRows.count(), 2);
  await popup.getByRole('button', { name: 'Afdrukken / opslaan als PDF' }).click();
  assert.equal(await popup.evaluate(() => window.__reviewTableWasOpenForPrint), true);
  assert.equal(await popup.evaluate(() => window.__filterStatusAtPrint), 'Toont 6 synthetische signalen.');
  assert.equal(await popup.evaluate(() => window.__fixtureRowsAtPrint), 6);
  assert.equal(await eventRows.count(), 2, 'printing restores the on-screen filter after the dialog');
  assert.equal(await reviewDetails.locator('table').isVisible(), false);
  await popup.evaluate(() => {
    window.print = () => { throw new Error('print unavailable'); };
  });
  const printError = new Promise(resolve => popup.once('pageerror', resolve));
  await popup.getByRole('button', { name: 'Afdrukken / opslaan als PDF' }).click();
  assert.match((await printError).message, /print unavailable/);
  assert.equal(await eventRows.count(), 2, 'failed printing restores the active filter');
  assert.equal(await reviewDetails.locator('table').isVisible(), false, 'failed printing restores disclosure state');
  await popup.emulateMedia({ media: 'print' });
  assert.equal(await popup.getByRole('button', { name: 'Afdrukken / opslaan als PDF' }).isVisible(), false);
  assert.equal(await popup.locator('.filter-group').evaluate(group => getComputedStyle(group).display), 'none');
  await reviewDetails.evaluate(details => { details.open = true; });
  assert.equal(await reviewDetails.locator('table').isVisible(), true);
  assert.equal(await popup.locator('.table-wrap').evaluate(table => getComputedStyle(table).overflowX), 'visible');
  assert.equal(await popup.locator('.events-panel tbody tr').count(), 2);
  await popup.emulateMedia({ media: 'screen' });
  const documentOrigin = new URL(popup.url()).origin;
  const remoteRequests = [];
  popup.on('request', request => {
    if (new URL(request.url()).origin !== documentOrigin) remoteRequests.push(request.url());
  });
  await popup.reload();
  await popup.getByRole('heading', { name: 'Signal overview' }).waitFor();
  assert.deepEqual(remoteRequests, []);

  assert.equal(await eventRows.count(), 6);
  assert.equal(await popup.getByRole('group', { name: 'Filter synthetische signalen' }).count(), 1);
  assert.equal(await popup.locator('.events-panel caption').textContent(), 'Vaste synthetische signalen, gefilterd op ernst');
  assert.deepEqual(await popup.locator('.events-panel thead th').evaluateAll(headers =>
    headers.map(header => header.getAttribute('scope'))), Array(7).fill('col'));
  const filterStatus = popup.locator('.events-panel [role="status"]');
  assert.equal((await filterStatus.textContent()).trim(), 'Toont 6 synthetische signalen.');
  for (const [severity, count, announcement] of [
    ['Hoog', 2, 'Toont 2 synthetische signalen met ernst Hoog.'],
    ['Middel', 1, 'Toont 1 synthetisch signaal met ernst Middel.'],
    ['Laag', 3, 'Toont 3 synthetische signalen met ernst Laag.'],
    ['Alles', 6, 'Toont 6 synthetische signalen.']
  ]) {
    const button = popup.getByRole('button', { name: severity, exact: true });
    await button.click();
    assert.equal(await eventRows.count(), count, `${severity} filter should show ${count} fixture rows`);
    assert.equal(await button.getAttribute('aria-pressed'), 'true');
    assert.equal((await filterStatus.textContent()).trim(), announcement);
  }

  await popup.setViewportSize({ width: 390, height: 844 });
  const layout = await popup.evaluate(() => {
    const table = document.querySelector('.table-wrap');
    return {
      viewportWidth: innerWidth,
      pageWidth: document.documentElement.scrollWidth,
      tableWidth: table.clientWidth,
      tableContentWidth: table.scrollWidth
    };
  });
  assert.ok(layout.pageWidth <= layout.viewportWidth, 'mobile dashboard must not overflow the page horizontally');
  assert.ok(layout.tableContentWidth > layout.tableWidth, 'wide event table should scroll within its own container on mobile');
  assert.equal(await popup.getByRole('button', { name: 'Alles', exact: true }).isVisible(), true);
  await context.close();
  console.log('PASS: NEO verified and opened 5CRIPTIE; fixture filters, responsive table containment, and synthetic-only content passed.');
} finally {
  await browser?.close();
  await scriptie?.stop();
  await launcher?.stop();
  fs.rmSync(launcherDirectory, { recursive: true, force: true });
  fs.rmSync(moduleDirectory, { recursive: true, force: true });
}
