// AETHER A10 browser acceptance. Run in a browser-capable environment:
//   npm ci && npm install --no-save playwright && node tests/browser-acceptance.cjs
// Set AETHER_CHROMIUM_PATH to the local Chromium executable if needed.
// This test never contacts BASTION or sends a real task.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const port = 5187;
const origin = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
  cwd: require('node:path').resolve(__dirname, '..'), stdio: 'ignore',
});

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function ready() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (server.exitCode !== null) throw new Error('Vite terminated before browser acceptance');
    try {
      const response = await fetch(origin);
      if (response.ok) return;
    } catch { /* server not yet ready */ }
    await delay(250);
  }
  throw new Error('Vite preview did not become reachable');
}

async function run() {
  let browser;
  try {
    await ready();
    browser = await chromium.launch({
      headless: true,
      ...(process.env.AETHER_CHROMIUM_PATH ? { executablePath: process.env.AETHER_CHROMIUM_PATH } : {}),
    });
    const page = await browser.newPage({ acceptDownloads: true });
    const requests = [];
    page.on('request', request => { if (request.method() === 'POST') requests.push(request.url()); });
    await page.goto(origin);
    await page.getByLabel('Bericht').fill('Synthetische AETHER-testtekst');
    await page.getByLabel(/Passphrase/).fill('synthetic test passphrase');
    await page.getByRole('button', { name: 'Versleutel' }).click();
    await page.getByRole('status').filter({ hasText: 'Versleuteld.' }).waitFor();
    assert.equal(await page.getByLabel('Bericht').inputValue(), '');
    assert.equal(await page.getByLabel(/Passphrase/).inputValue(), '');
    const ciphertext = await page.getByLabel('Versleutelde tekst').inputValue();
    assert.equal(JSON.parse(ciphertext).version, 1);
    assert.ok(!ciphertext.includes('Synthetische AETHER-testtekst'));

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Bewaar versleuteld bestand' }).click();
    const download = await downloadPromise;
    assert.equal(download.suggestedFilename(), 'aether-envelope-v1.json');

    // A valid import replaces and clears any existing readable draft.
    await page.getByLabel('Bericht').fill('Tijdelijk concept');
    await page.getByLabel(/Passphrase/).fill('another test passphrase');
    await page.locator('#encrypted-file').setInputFiles({
      name: 'aether-envelope-v1.json', mimeType: 'application/json', buffer: Buffer.from(ciphertext),
    });
    await page.getByRole('status').filter({ hasText: 'lokaal geladen' }).waitFor();
    assert.equal(await page.getByLabel('Bericht').inputValue(), '');
    assert.equal(await page.getByLabel(/Passphrase/).inputValue(), '');
    assert.equal(await page.getByLabel('Versleutelde tekst').inputValue(), ciphertext);
    assert.deepEqual(requests, [], 'Import and export must not send POST requests');

    await page.getByRole('button', { name: 'Wis versleuteld resultaat' }).click();
    assert.equal(await page.getByLabel('Versleutelde tekst').count(), 0);
    await page.locator('#encrypted-file').setInputFiles({
      name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from('{"version":0}'),
    });
    await page.getByRole('alert').filter({ hasText: 'Import geweigerd' }).waitFor();
    assert.equal(await page.getByLabel('Versleutelde tekst').count(), 0);
    assert.deepEqual(requests, []);
    console.log('AETHER A10 browser acceptance: PASS (synthetic offline flows only)');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
