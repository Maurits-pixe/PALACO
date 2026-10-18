import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { X509Certificate, createHash } from 'node:crypto';
import { chromium } from 'playwright';
import { CATALOG } from '../src/catalog.js';
import { createReport, root } from './report.mjs';
import { temporarySubject, certificates, metadataFixtures, viteProcess, waitForHttps } from './local-fixtures.mjs';

const report = createReport('browser', import.meta.url, [
  'Real Chromium loads the production-built Vue SFC and emitted JSON Worker through actual local Vite HTTPS preview.',
  'Positive browser fixtures use ignoreHTTPSErrors only for their disposable test CA. No OS/browser trust installation or claim of mkcert trust.',
  'CORS and redirect enforcement remain enabled. A separate normal TLS context must reject the untrusted fixture.',
  'The successor aether.hoofdkantoor.info response and a deliberately spinning worker are explicitly intercepted fixtures; no real external app is contacted.',
  'One TTL check waits a real 60 seconds; a separate clock test uses Playwright simulated time.',
  'No hosted Site, existing user session, full DRAFT contract, cross-browser acceptance, CI or deployment.'
]);
const selected = process.env.PALACO_BROWSER_TEST_FILTER ? new Set(process.env.PALACO_BROWSER_TEST_FILTER.split(',')) : null;
const originalCheck = report.check;
report.check = (id, fn, method) => !selected || selected.has(id) || id === 'BROWSER-HARNESS-COMPLETED' ? originalCheck(id, fn, method) : Promise.resolve();
const directory = temporarySubject('browser');
const tls = certificates(directory);
const publicCaFile = 'browser-fixture-ca-public.pem';
fs.writeFileSync(path.join(root, 'evidence', publicCaFile), tls.ca);
const fixture = await metadataFixtures(tls);
let server = viteProcess(directory, true);
let browser;
let context;
let page;
const pageErrors = [];
let setupError = null;
const runtimeConfig = process.env.PALACO_BROWSER_RUNTIME_CONFIG
  ? JSON.parse(fs.readFileSync(process.env.PALACO_BROWSER_RUNTIME_CONFIG, 'utf8')) : {};
const dangerous = ['--disable-web-security', '--allow-running-insecure-content', '--ignore-certificate-errors'];
if ((runtimeConfig.args || []).some(arg => dangerous.some(flag => arg === flag || arg.startsWith(flag + '=')))) {
  throw new Error('Browser harness rejects disabled web security, mixed-content or global certificate bypass flags.');
}
const card = id => page.locator(`[data-module="${id}"]`);
async function status(id, text, timeout = 7500) {
  await card(id).locator('[data-status]').filter({ hasText: text }).waitFor({ timeout });
  assert.equal((await card(id).locator('[data-status]').textContent()).trim(), text);
}
async function fresh() {
  fixture.config.aether.mode = 'ok';
  await page.goto('https://127.0.0.1:5173');
  await card('aether').locator('input').waitFor();
}
async function verify(id = 'aether', origin = 'https://localhost:5174') {
  await card(id).locator('input').fill(origin);
  await card(id).locator('[data-verify]').click();
}

try {
  await waitForHttps(server, tls.ca);
  browser = await chromium.launch({ headless: true, ...(runtimeConfig.executablePath ? { executablePath: runtimeConfig.executablePath } : {}), args: runtimeConfig.args || [] });
  await report.check('BROWSER-DEFAULT-TLS-REJECTION', async () => {
    const normal = await browser.newContext({ ignoreHTTPSErrors: false });
    try {
      const normalPage = await normal.newPage();
      await assert.rejects(normalPage.goto('https://127.0.0.1:5173', { timeout: 5000 }));
      return { untrustedFixtureAccepted: false };
    } finally { await normal.close(); }
  }, 'native Chromium certificate enforcement; no TLS bypass');
  context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1360, height: 900 } });
  await context.addInitScript(() => {
    const NativeWorker = window.Worker;
    const stats = window.__palacoWorkerStats = { created: 0, terminated: 0 };
    window.Worker = class extends NativeWorker {
      constructor(...args) { super(...args); stats.created++; }
      terminate(...args) { stats.terminated++; return super.terminate(...args); }
    };
  });
  page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  await report.check('BROWSER-VUE-INITIAL-DESKTOP', async () => {
    await fresh(); assert.equal(await page.locator('[data-module]').count(), 3);
    for (const id of ['aether', 'bastion', '5criptie']) {
      await status(id, 'Niet ingesteld'); assert.equal(await card(id).locator('[data-launch]').isDisabled(), true);
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(root, 'evidence/desktop-initial.png'), fullPage: true });
    return { cards: 3, horizontalOverflow: false, viewport: { width: 1360, height: 900 } };
  }, 'production-built Vue mount, native DOM, real HTTPS preview');
  await report.check('BROWSER-MODULE-ACCESSIBLE-CONTROLS', async () => {
    await fresh();
    for (const { name } of CATALOG) {
      const form = page.getByRole('form', { name, exact: true });
      assert.equal(await form.count(), 1);
      assert.equal(await form.getByRole('textbox', { name: `Toegestane HTTPS-origin voor ${name}`, exact: true }).count(), 1);
      assert.equal(await form.getByRole('button', { name: `Opslaan & verifiëren ${name}`, exact: true }).isDisabled(), true);
      assert.equal(await form.getByRole('button', { name: `Wissen ${name}`, exact: true }).isDisabled(), true);
      assert.equal(await page.getByRole('button', { name: `Wacht op verificatie ${name}`, exact: true }).isDisabled(), true);
    }
    const input = page.getByRole('textbox', { name: 'Toegestane HTTPS-origin voor AETHER', exact: true });
    fixture.config.aether.mode = 'no-response';
    await input.fill('https://localhost:5174');
    await page.getByRole('button', { name: 'Opslaan & verifiëren AETHER', exact: true }).click();
    await status('aether', 'Controleren…');
    assert.equal(await page.getByRole('button', { name: 'Controleren… AETHER', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: 'Annuleren AETHER', exact: true }).click();
    await status('aether', 'Niet ingesteld');
    fixture.config.aether.mode = 'ok';
    await page.getByRole('button', { name: 'Opslaan & verifiëren AETHER', exact: true }).click();
    await status('aether', 'Modulemetadata bevestigd');
    assert.equal(await page.getByRole('button', { name: 'Open module AETHER', exact: true }).isEnabled(), true);
    await page.getByRole('button', { name: 'Wissen AETHER', exact: true }).click();
    assert.equal(await input.inputValue(), '');
    await status('bastion', 'Niet ingesteld');
    return { namedForms: 3, moduleSpecificActions: true, roleBasedInteraction: true };
  }, 'Chromium role/name locators distinguish module controls through pending, cancelled and verified states; not a screen-reader audit');
  await report.check('BROWSER-CANCEL-CLEAR-KEYBOARD-FOCUS', async () => {
    await fresh();
    for (const { id, origins } of CATALOG) {
      const input = card(id).locator('input');
      fixture.config[id].mode = 'no-response';
      await verify(id, origins[0]); await status(id, 'Controleren…');
      const before = fixture.requests.length;
      const cancel = card(id).locator('[data-cancel]');
      await cancel.focus(); await cancel.press('Enter');
      await status(id, 'Niet ingesteld');
      assert.equal(await input.evaluate(element => element === document.activeElement), true);
      assert.equal(await input.inputValue(), origins[0]);
      assert.equal(await card(id).locator('[data-cancel]').count(), 0);
      const clear = card(id).locator('[data-clear]');
      await clear.focus(); await clear.press('Space');
      assert.equal(await input.evaluate(element => element === document.activeElement), true);
      assert.equal(await input.inputValue(), '');
      assert.equal(await clear.isDisabled(), true);
      assert.equal(fixture.requests.length, before);
      fixture.config[id].mode = 'ok';
    }
    return { testedModules: CATALOG.length, focusTarget: 'same module origin input', additionalRequests: 0 };
  }, 'native keyboard activation restores focus before cancel disappears or clear becomes disabled');
  await report.check('BROWSER-LAUNCHER-ORIGIN', async () => {
    await page.goto('https://127.0.0.1:5173/?review=local-only#preview');
    const origin = page.locator('[data-launcher-origin]');
    await origin.waitFor();
    assert.equal(await origin.textContent(), 'https://127.0.0.1:5173');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    return { displayedOrigin: await origin.textContent(), excludesPathQueryFragment: true };
  }, 'production-built Vue renders the actual browser origin, not a configured deployment URL');
  await report.check('BROWSER-ACTUAL-PREVIEW-HEADERS', async () => {
    const response = await page.goto('https://127.0.0.1:5173');
    const headers = response.headers();
    assert.match(headers['content-security-policy'], /frame-ancestors 'none'/);
    assert.match(headers['content-security-policy'], /worker-src 'self'/);
    assert.equal(headers['x-content-type-options'], 'nosniff');
    assert.equal(headers['referrer-policy'], 'no-referrer');
    assert.equal(headers['cache-control'], 'no-store');
    assert.match(headers['permissions-policy'], /microphone=\(\)/);
    return { scope: 'local built preview', headers };
  }, 'actual HTTPS document response inspected in Chromium');
  await report.check('BROWSER-ORIGIN-CHOICES-NO-REQUEST', async () => {
    await fresh();
    const before = fixture.requests.length;
    const metadataRequests = [];
    const onRequest = request => {
      if (new URL(request.url()).pathname === '/.well-known/palaco-app.json') metadataRequests.push(request.url());
    };
    page.on('request', onRequest);
    try {
      for (const { id, origins } of CATALOG) {
        const choices = card(id).locator('[data-origin-choice]');
        await card(id).locator('.origin-choices summary').click();
        assert.deepEqual(await choices.allTextContents(), origins);
        for (const [index, origin] of origins.entries()) {
          await choices.nth(index).click();
          assert.equal(await card(id).locator('input').inputValue(), origin);
          await status(id, 'Niet ingesteld');
          assert.equal(await card(id).locator('[data-launch]').isDisabled(), true);
          assert.equal(await card(id).locator('[data-verify]').isEnabled(), true);
        }
      }
      assert.equal(fixture.requests.length, before);
      assert.deepEqual(metadataRequests, []);
      return { modules: CATALOG.length, metadataRequests: 0, automaticVerification: false };
    } finally { page.off('request', onRequest); }
  }, 'native DOM clicks on every catalog origin; selection only, no metadata fetch');
  await report.check('BROWSER-ORIGIN-CHOICE-REVOKES-VERIFICATION', async () => {
    await fresh();
    await verify();
    await status('aether', 'Modulemetadata bevestigd');
    const before = fixture.requests.length;
    await card('aether').locator('.origin-choices summary').click();
    await card('aether').locator('[data-origin-choice]').first().click();
    await status('aether', 'Niet ingesteld');
    assert.equal(await card('aether').locator('[data-launch]').isDisabled(), true);
    assert.equal(await card('aether').locator('.check-details').count(), 0);
    assert.equal(fixture.requests.length, before);
    return { reselectedSameOrigin: true, verificationRevoked: true, additionalRequests: 0 };
  }, 'reselecting even the verified origin requires a new explicit verification');
  await report.check('BROWSER-ORIGIN-CHOICE-CANCELS-PENDING', async () => {
    await fresh(); fixture.config.aether.mode = 'race';
    const request = page.waitForRequest('https://localhost:5174/.well-known/palaco-app.json');
    await verify(); await request;
    await card('aether').locator('.origin-choices summary').click();
    await card('aether').locator('[data-origin-choice]').nth(1).click();
    await status('aether', 'Niet ingesteld');
    await page.waitForTimeout(1900);
    await status('aether', 'Niet ingesteld');
    assert.equal(await card('aether').locator('input').inputValue(), CATALOG[0].origins[1]);
    assert.equal(await card('aether').locator('[data-launch]').isDisabled(), true);
    assert.equal(await card('aether').locator('[data-cancel]').count(), 0);
    return { pendingCheckRevoked: true, staleResultAccepted: false };
  }, 'native choice button cancels an active HTTPS check with a delayed fixture body');
  await report.check('BROWSER-CLEAR-MODULE-STATE', async () => {
    await fresh();
    assert.equal(await card('aether').locator('[data-clear]').isDisabled(), true);
    await verify('bastion', 'https://localhost:5175');
    await status('bastion', 'Modulemetadata bevestigd');
    for (const mode of ['invalid-input', 'verified']) {
      if (mode === 'invalid-input') await card('aether').locator('input').fill('http://invalid.example');
      else { await verify(); await status('aether', 'Modulemetadata bevestigd'); }
      const before = fixture.requests.length;
      await card('aether').locator('[data-clear]').click();
      await status('aether', 'Niet ingesteld');
      assert.equal(await card('aether').locator('input').inputValue(), '');
      assert.equal(await card('aether').locator('.error-msg, .check-details, [data-countdown]').count(), 0);
      for (const control of ['clear', 'verify', 'launch']) {
        assert.equal(await card('aether').locator(`[data-${control}]`).isDisabled(), true);
      }
      await status('bastion', 'Modulemetadata bevestigd');
      assert.equal(fixture.requests.length, before);
    }
    return { clearedInputAndHistory: true, otherModulePreserved: true, additionalRequests: 0 };
  }, 'actual clear button resets invalid and verified local state without fetching or changing another module');
  await report.check('BROWSER-CLEAR-PENDING-CHECK', async () => {
    await fresh(); fixture.config.aether.mode = 'race';
    const request = page.waitForRequest('https://localhost:5174/.well-known/palaco-app.json');
    await verify(); await request;
    await card('aether').locator('[data-clear]').click();
    await status('aether', 'Niet ingesteld');
    await page.waitForTimeout(1900);
    await status('aether', 'Niet ingesteld');
    assert.equal(await card('aether').locator('input').inputValue(), '');
    assert.equal(await card('aether').locator('[data-cancel], .check-details, .error-msg').count(), 0);
    assert.equal(await card('aether').locator('[data-launch]').isDisabled(), true);
    fixture.config.aether.mode = 'ok';
    await verify(); await status('aether', 'Modulemetadata bevestigd');
    return { staleResultAccepted: false, explicitReverificationWorks: true };
  }, 'clear cancels an active HTTPS check and ignores its late result; explicit subsequent check succeeds');
  await report.check('BROWSER-ALL-THREE-METADATA-AND-WORKER', async () => {
    await fresh();
    for (const [id, port] of [['aether', 5174], ['bastion', 5175], ['5criptie', 5176]]) {
      await verify(id, `https://localhost:${port}`); await status(id, 'Modulemetadata bevestigd');
      assert.equal(await card(id).locator('[data-launch]').isEnabled(), true);
    }
    await page.screenshot({ path: path.join(root, 'evidence/desktop-verified.png'), fullPage: true });
    return { moduleIds: ['aether', 'bastion', '5criptie'], transport: 'native HTTPS Fetch, CORS, stream and emitted JSON Worker' };
  }, 'real browser Fetch/Worker with TLS fixtures and restrictive CORS headers');
  for (const [id, mode, label, code] of [
    ['BROWSER-SCHEMA-MISSING-STATUS', 'missing-status', 'Verificatie mislukt', 'SCHEMA_STATUS'],
    ['BROWSER-IDENTITY-MISMATCH', 'wrong-id', 'Verificatie mislukt', 'IDENTITY'],
    ['BROWSER-JSON-MALFORMED', 'malformed', 'Verificatie mislukt', 'JSON_INVALID'],
    ['BROWSER-CORS-REFUSAL', 'no-cors', 'Controle niet mogelijk', 'TRANSPORT'],
    ['BROWSER-REDIRECT-REFUSAL', 'redirect', 'Controle niet mogelijk', 'TRANSPORT']
  ]) await report.check(id, async () => {
    await fresh(); fixture.config.aether.mode = mode;
    await verify(); await status('aether', label);
    assert.equal(await card('aether').locator('[data-launch]').isDisabled(), true);
    assert.equal(await card('aether').locator('[data-error-code] code').textContent(), code);
    return { mode, label, detail: await card('aether').locator('.error-msg').textContent() };
  }, 'native browser Fetch/Worker; actual local fixture response/CORS/redirect');
  await report.check('BROWSER-ERROR-CODE-LIFECYCLE', async () => {
    await fresh(); fixture.config.aether.mode = 'wrong-id';
    await verify(); await status('aether', 'Verificatie mislukt');
    assert.equal(await card('aether').locator('[data-error-code] code').textContent(), 'IDENTITY');
    await card('aether').locator('input').fill('https://localhost:5174/invalid');
    assert.equal(await card('aether').locator('[data-error-code]').count(), 0);
    await card('aether').locator('[data-clear]').click();
    assert.equal(await card('aether').locator('[data-error-code]').count(), 0);
    fixture.config.aether.mode = 'race';
    await verify(); await status('aether', 'Controleren…');
    assert.equal(await card('aether').locator('[data-error-code]').count(), 0);
    await card('aether').locator('[data-cancel]').click();
    assert.equal(await card('aether').locator('[data-error-code]').count(), 0);
    fixture.config.aether.mode = 'ok';
    await verify(); await status('aether', 'Modulemetadata bevestigd');
    assert.equal(await card('aether').locator('[data-error-code]').count(), 0);
    return { staleCodeAfterEditClearCancelOrSuccess: false };
  }, 'visible diagnostic code follows the existing controller state without retaining a previous failure');
  await report.check('BROWSER-METADATA-RESULT-TEXT', async () => {
    await fresh();
    const endpoint = 'https://localhost:5174/.well-known/palaco-app.json';
    const reportedStatus = '<img src=x onerror="alert(1)"> & niet-operationeel';
    await page.route(endpoint, route => route.fulfill({
      status: 200, contentType: 'application/json',
      headers: { 'access-control-allow-origin': 'https://127.0.0.1:5173' },
      body: JSON.stringify({ appId: 'aether', status: reportedStatus })
    }));
    try {
      await verify(); await status('aether', 'Modulemetadata bevestigd');
      assert.equal(await card('aether').locator('[data-checked-origin] code').textContent(), 'https://localhost:5174');
      assert.equal(await card('aether').locator('[data-reported-status] code').textContent(), JSON.stringify(reportedStatus));
      assert.equal(await card('aether').locator('[data-reported-status] img').count(), 0);
      await card('aether').locator('input').fill('https://aether.hoofdkantoor.info');
      assert.equal(await card('aether').locator('[data-checked-origin], [data-reported-status]').count(), 0);
      return { renderedAsText: true, statusInterpretedAsHealth: false, clearedOnEdit: true };
    } finally { await page.unroute(endpoint); }
  }, 'intercepted metadata fixture, not a real module; Vue text interpolation never renders received markup');
  await report.check('BROWSER-ENTER-VERIFIES-WITHOUT-LAUNCH', async () => {
    await fresh();
    const before = fixture.requests.length;
    const url = page.url();
    const tabs = context.pages().length;
    const input = card('aether').locator('input');
    await input.fill('https://localhost:5174');
    await input.press('Enter');
    await status('aether', 'Modulemetadata bevestigd');
    assert.equal(fixture.requests.length, before + 1);
    assert.equal(page.url(), url);
    assert.equal(context.pages().length, tabs);
    await status('bastion', 'Niet ingesteld');
    return { metadataRequests: 1, navigation: false, moduleOpened: false };
  }, 'native Enter submits only the selected module form and verifies without navigation or launch');
  await report.check('BROWSER-ENTER-INVALID-AND-PENDING', async () => {
    await fresh();
    const input = card('aether').locator('input');
    const before = fixture.requests.length;
    for (const value of ['', 'https://localhost:5174/invalid']) {
      await input.fill(value);
      await input.press('Enter');
      assert.equal(fixture.requests.length, before);
      assert.equal(await card('aether').locator('[data-verify]').isDisabled(), true);
    }
    fixture.config.aether.mode = 'race';
    await input.fill('https://localhost:5174');
    const request = page.waitForRequest('https://localhost:5174/.well-known/palaco-app.json');
    await input.press('Enter'); await request;
    await status('aether', 'Controleren…');
    await input.press('Enter');
    await input.press('Enter');
    await status('aether', 'Modulemetadata bevestigd');
    assert.equal(fixture.requests.length, before + 1);
    return { invalidInputRequests: 0, pendingCheckRequests: 1 };
  }, 'native Enter rejects invalid input and does not restart or duplicate a pending check');
  await report.check('BROWSER-ORIGIN-PATH-NO-REQUEST', async () => {
    await fresh(); const before = fixture.requests.length;
    await card('aether').locator('input').fill('https://localhost:5174/somepath');
    assert.equal(await card('aether').locator('[data-verify]').isDisabled(), true);
    assert.match(await card('aether').locator('.error-msg').textContent(), /URL mag geen pad/);
    assert.equal(fixture.requests.length, before);
    return { metadataRequests: 0, verifyDisabled: true };
  }, 'native browser input validation; no network request');
  await report.check('BROWSER-UI-SUPERSEDE', async () => {
    await fresh(); fixture.config.aether.mode = 'race';
    const firstRequest = page.waitForRequest('https://localhost:5174/.well-known/palaco-app.json');
    await verify(); await firstRequest;
    assert.equal(await card('aether').locator('input').isEnabled(), true);
    await page.route('https://aether.hoofdkantoor.info/.well-known/palaco-app.json', route => route.fulfill({
      status: 200, contentType: 'application/json',
      headers: { 'access-control-allow-origin': 'https://127.0.0.1:5173' },
      body: JSON.stringify({ appId: 'aether', status: 'successor-fixture' })
    }));
    try {
      await card('aether').locator('input').fill('https://aether.hoofdkantoor.info');
      await status('aether', 'Niet ingesteld');
      await card('aether').locator('[data-verify]').click(); await status('aether', 'Modulemetadata bevestigd');
      await page.waitForTimeout(1900);
      assert.equal(await card('aether').locator('input').inputValue(), 'https://aether.hoofdkantoor.info');
      await status('aether', 'Modulemetadata bevestigd');
      return { origin: 'https://aether.hoofdkantoor.info', firstBodyDelayMs: 1800, inputEditableDuringCheck: true,
        successorTransport: 'intercepted fixture, not the real domain' };
    } finally { await page.unroute('https://aether.hoofdkantoor.info/.well-known/palaco-app.json'); }
  }, 'real input/button interaction and first native HTTPS request; explicitly intercepted successor metadata');
  await report.check('BROWSER-CANCEL-AND-RETRY', async () => {
    await fresh(); fixture.config.aether.mode = 'no-response'; await verify();
    await card('aether').locator('[data-cancel]').click(); await status('aether', 'Niet ingesteld');
    assert.equal(await card('aether').locator('[data-verify]').isEnabled(), true);
    fixture.config.aether.mode = 'ok'; await card('aether').locator('[data-verify]').click();
    await status('aether', 'Modulemetadata bevestigd'); return { cancelRestoredInput: true, retryVerified: true };
  }, 'native DOM interaction and actual HTTPS Fetch abort/retry');
  await report.check('BROWSER-TIMEOUT-SLOW-BODY', async () => {
    await fresh(); fixture.config.aether.mode = 'slow-body';
    const start = performance.now(); await verify(); await status('aether', 'Controle niet mogelijk');
    const elapsedMs = performance.now() - start;
    assert.match(await card('aether').locator('.error-msg').textContent(), /Time-out/);
    await page.waitForTimeout(400); await status('aether', 'Controle niet mogelijk');
    return { elapsedMs, bodyDelayMs: 5200, verifiedAfterDeadline: false };
  }, 'native Chromium Fetch and response stream; real 5200ms body delay');
  await report.check('BROWSER-PARSE-WORKER-TIMEOUT-AND-RECOVERY', async () => {
    await fresh(); let intercepted = 0;
    const workerRoute = /\/assets\/json-worker-[^/]+\.js$/;
    await page.route(workerRoute, route => { intercepted++; return route.fulfill({
      status: 200, contentType: 'application/javascript', body: 'self.onmessage=()=>{while(true){}};' }); });
    try {
      await verify(); await status('aether', 'Controle niet mogelijk');
      assert.equal(intercepted, 1); assert.match(await card('aether').locator('.error-msg').textContent(), /Time-out/);
      assert.equal(await card('aether').locator('[data-verify]').isEnabled(), true);
      assert.deepEqual(await page.evaluate(() => window.__palacoWorkerStats), { created: 1, terminated: 1 });
    } finally { await page.unroute(workerRoute); }
    await card('aether').locator('[data-verify]').click(); await status('aether', 'Modulemetadata bevestigd');
    return { interceptedSpinningWorker: true, timeoutRefused: true, nextActualWorkerSucceeded: true,
      workerStats: await page.evaluate(() => window.__palacoWorkerStats) };
  }, 'real Worker and production adapter; replaced spinning script; transparent native Worker termination counter');
  await report.check('BROWSER-REACTIVE-COUNTDOWN-AND-REAL-TTL', async () => {
    await fresh(); await verify(); await status('aether', 'Modulemetadata bevestigd');
    const start = performance.now();
    const first = await card('aether').locator('[data-countdown]').textContent();
    await page.waitForTimeout(1300);
    const second = await card('aether').locator('[data-countdown]').textContent();
    assert.notEqual(first, second);
    console.log(JSON.stringify({ progress: 'real 60-second TTL started', first, second }));
    await status('aether', 'Verificatie verlopen', 62000);
    assert.equal(await card('aether').locator('[data-launch]').isDisabled(), true);
    return { first, second, elapsedMs: performance.now() - start, realWallClockWait: true, launchDisabled: true };
  }, 'actual browser render/timers and real 60-second validity period; no simulated clock');
  await report.check('BROWSER-RETURN-REVOKES-VERIFICATION', async () => {
    await fresh(); await verify(); await status('aether', 'Modulemetadata bevestigd');
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await status('aether', 'Verificatie verlopen'); return { returnRequiresNewCheck: true, event: 'synthetic focus dispatch in native browser' };
  }, 'actual Vue event handler and DOM; explicitly synthetic lifecycle event');
  await report.check('BROWSER-SIMULATED-EXACT-TTL', async () => {
    const originalPage = page;
    const clockPage = await context.newPage();
    page = clockPage;
    try {
      await page.clock.install({ time: new Date('2026-10-07T00:00:00Z') });
      await page.clock.pauseAt(new Date('2026-10-07T00:00:01Z'));
      await fresh(); await verify(); await status('aether', 'Modulemetadata bevestigd');
      await page.clock.fastForward(59999);
      await status('aether', 'Modulemetadata bevestigd');
      await page.clock.fastForward(1);
      await status('aether', 'Verificatie verlopen');
      assert.equal(await card('aether').locator('[data-launch]').isDisabled(), true);
      assert.equal(await card('aether').locator('[data-checked-origin], [data-reported-status]').count(), 0);
      return { simulatedElapsedMs: 60000, verifiedAt59999: true, expiredAt60000: true };
    } finally { await clockPage.close(); page = originalPage; }
  }, 'native Vue/browser with explicitly simulated Playwright timers/performance/wallclock');
  await report.check('BROWSER-LAUNCH-NOOPENER', async () => {
    await fresh(); await verify(); await status('aether', 'Modulemetadata bevestigd');
    const popupReady = context.waitForEvent('page');
    await card('aether').locator('[data-launch]').click();
    const popup = await popupReady;
    try {
      await popup.waitForLoadState('domcontentloaded');
      assert.equal(new URL(popup.url()).origin, 'https://localhost:5174');
      assert.equal(await popup.evaluate(() => window.opener === null), true);
      assert.match(await popup.locator('h1').textContent(), /TEST FIXTURE/);
      return { origin: new URL(popup.url()).origin, openerIsNull: true, actualModuleApp: false };
    } finally { await popup.close(); }
  }, 'native window.open to the local verified fixture and actual null opener');
  await report.check('BROWSER-MOBILE-NO-OVERFLOW', async () => {
    await page.setViewportSize({ width: 390, height: 844 }); await fresh();
    for (const { id } of CATALOG) await card(id).locator('.origin-choices summary').click();
    await card('aether').locator('input').fill('https://localhost:5174/long-invalid-path-for-error-layout');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(root, 'evidence/mobile-error.png'), fullPage: true });
    return { viewport: { width: 390, height: 844 }, horizontalOverflow: false };
  }, 'native Chromium mobile viewport, real input/error layout');
  await report.check('BROWSER-VUE-UNMOUNT-CLEANS-WORKER', async () => {
    await server.stop();
    fs.copyFileSync(path.join(root, 'tests/vue-lifecycle.html'), path.join(directory, 'lifecycle.html'));
    fs.copyFileSync(path.join(root, 'tests/vue-lifecycle.js'), path.join(directory, 'lifecycle.js'));
    server = viteProcess(directory, false); await waitForHttps(server, tls.ca);
    await page.goto('https://127.0.0.1:5173/lifecycle.html');
    fixture.config.aether.mode = 'ok';
    const workerRoute = /\/src\/json-worker\.js(?:\?.*)?$/;
    await page.route(workerRoute, route => route.fulfill({ status: 200, contentType: 'application/javascript', body: 'self.onmessage=()=>{while(true){}};' }));
    try {
      await verify(); await page.waitForFunction(() => window.__palacoWorkerStats.created === 1);
      await page.locator('[data-host-unmount]').click();
      await page.waitForFunction(() => window.__palacoWorkerStats.terminated === 1);
      assert.equal(await page.locator('#app > *').count(), 0);
    } finally { await page.unroute(workerRoute); }
    await page.locator('[data-host-mount]').click();
    await status('aether', 'Niet ingesteld');
    await verify(); await status('aether', 'Modulemetadata bevestigd');
    return { unmountedAppEmpty: true, remountedStateFresh: true,
      workerStats: await page.evaluate(() => window.__palacoWorkerStats), mode: 'actual App.vue in a separate Vite dev component host' };
  }, 'actual Vue createApp/unmount, production component lifecycle, real worker termination and fresh remount');
  await report.check('BROWSER-MOBILE-NATIVE-TAP', async () => {
    const oldPage = page;
    const mobile = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    page = await mobile.newPage();
    try {
      await fresh();
      await card('aether').locator('input').fill('https://localhost:5174');
      await card('aether').locator('[data-verify]').tap();
      await status('aether', 'Modulemetadata bevestigd');
      const opened = mobile.waitForEvent('page');
      await card('aether').locator('[data-launch]').tap();
      const popup = await opened;
      await popup.waitForLoadState('domcontentloaded');
      assert.equal(new URL(popup.url()).origin, 'https://localhost:5174');
      assert.equal(await popup.evaluate(() => window.opener === null), true);
      return { nativeTap: true, actualModuleApp: false, openerIsNull: true };
    } finally { await mobile.close(); page = oldPage; }
  }, 'Chromium touchscreen context; actual tap on verify and launch; disposable HTTPS fixture');
  await report.check('BROWSER-NO-UNHANDLED-PAGE-ERRORS', async () => {
    assert.deepEqual(pageErrors, []); return { pageErrors };
  }, 'native Chromium unhandled pageerror events across the suite');
} catch (error) {
  setupError = error.stack;
  await report.check('BROWSER-HARNESS-COMPLETED', async () => { throw error; }, 'browser harness setup/execution');
} finally {
  const browserVersion = browser ? browser.version() : null;
  await context?.close(); await browser?.close();
  await server.stop(); await fixture.close();
  fs.rmSync(directory, { recursive: true, force: true });
  report.finish({ selectedTests: selected ? [...selected] : 'all', browserVersion, playwrightVersion: JSON.parse(fs.readFileSync(path.join(root, 'node_modules/playwright/package.json'))).version,
    browserArgs: runtimeConfig.args || [], browserBundleVersion: runtimeConfig.bundleVersion || null,
    executableSha256: runtimeConfig.executablePath ? createHash('sha256').update(fs.readFileSync(runtimeConfig.executablePath)).digest('hex') : null,
    fixtureCaFingerprint256: new X509Certificate(tls.ca).fingerprint256, publicCaFile, setupError });
}
