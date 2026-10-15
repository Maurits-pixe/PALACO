import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { after, before, test } from 'node:test';
import { chromium, expect } from '@playwright/test';

// Presentation proof only: real checked-in assets, no service, credentials or IdP.
// Every request is intercepted; only the three assets and one closed account read exist.
const ORIGIN = 'https://rio-ui.invalid';
const EMPTY_TITLE = 'Jouw titel verschijnt hier';
const EMPTY_NOTE = 'Je notitie krijgt hier de ruimte.';
const IMPORT_ERROR = 'Dit is geen geldig lokaal conceptbestand. Er is niets gewijzigd.';
const AUTHORITY = {
  accountActive: false, canOpenContact: false, operativeAuthority: 'NONE', consentGranted: false,
};
const assetDefinitions = [
  ['/', 'index.html', 'text/html; charset=utf-8'],
  ['/app.js', 'app.js', 'text/javascript; charset=utf-8'],
  ['/app.css', 'app.css', 'text/css; charset=utf-8'],
];
let browser;
let assets;

before(async () => {
  assets = new Map(await Promise.all(assetDefinitions.map(async ([path, name, contentType]) => [
    path, { body: await readFile(new URL(`../../services/rio-accounts/src/web/${name}`, import.meta.url)), contentType },
  ])));
  browser = await chromium.launch({ headless: true });
});
after(async () => { await browser?.close(); });

async function attachOfflineStudio(page) {
  const record = { writes: 0, authorityRequests: 0, accountReads: 0, pageErrors: 0 };
  page.on('pageerror', () => { record.pageErrors += 1; });
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!['GET', 'HEAD'].includes(request.method())) record.writes += 1;
    if (url.origin !== ORIGIN || request.method() !== 'GET' || url.search || url.hash) {
      record.authorityRequests += 1;
      await route.abort('blockedbyclient');
      return;
    }
    if (url.pathname === '/api/me') {
      record.accountReads += 1;
      await route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
    } else if (assets.has(url.pathname)) {
      await route.fulfill({ status: 200, ...assets.get(url.pathname) });
    } else {
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) {
        record.authorityRequests += 1;
      }
      await route.abort('blockedbyclient');
    }
  });
  await Promise.all([
    page.waitForResponse(response => response.url() === `${ORIGIN}/api/me` && response.status() === 401),
    page.goto(ORIGIN),
  ]);
  return record;
}

async function presentation(t, scenario) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }, acceptDownloads: true, serviceWorkers: 'block',
  });
  t.after(() => context.close());
  const page = await context.newPage();
  const record = await attachOfflineStudio(page);
  await scenario(page);
  assert.deepEqual(record, { writes: 0, authorityRequests: 0, accountReads: 1, pageErrors: 0 });
  assert.deepEqual(await context.cookies(), []);
  assert.deepEqual(await page.evaluate(async () => ({
    local: localStorage.length, session: sessionStorage.length,
    databases: (await indexedDB.databases()).length, caches: (await caches.keys()).length,
  })), { local: 0, session: 0, databases: 0, caches: 0 });
}

async function preview(page, title, note) {
  await expect(page.locator('#studio-preview-title')).toHaveJSProperty('textContent', title || EMPTY_TITLE);
  await expect(page.locator('#studio-preview-note')).toHaveJSProperty('textContent', note || EMPTY_NOTE);
  await expect(page.locator('#studio-title-count')).toHaveText(`${title.length} / 80`);
  await expect(page.locator('#studio-note-count')).toHaveText(`${note.length} / 2000`);
  await expect(page.locator('#studio-draft-state')).toHaveText(title || note ? 'Alleen in deze pagina' : 'Nog leeg');
}

function envelope(title, note) {
  return { schema: 'RIO_LOCAL_DRAFT_V1', verification: 'UNVERIFIED', authority: AUTHORITY, draft: { title, note } };
}

async function importDraft(page, value, name = 'rio-lokaal-concept.json') {
  await page.locator('#studio-import').setInputFiles({
    name, mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value), 'utf8'),
  });
}

async function exportedDraft(page) {
  const [download] = await Promise.all([
    page.waitForEvent('download'), page.locator('#studio-export').click(),
  ]);
  let completed = false;
  try {
    assert.equal(download.suggestedFilename(), 'rio-lokaal-concept.json');
    assert.equal(await download.failure(), null);
    const stream = await download.createReadStream();
    const chunks = [];
    let length = 0;
    for await (const chunk of stream) {
      length += chunk.length;
      assert.ok(length <= 12288);
      chunks.push(chunk);
    }
    const value = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    completed = true;
    return value;
  } finally {
    try { await download.delete(); } catch (error) { if (completed) throw error; }
  }
}

test('local Studio starts empty with existing labels and silent preview descriptions', { timeout: 45_000 }, async t => {
  await presentation(t, async page => {
    await preview(page, '', '');
    await expect(page.getByLabel('Titel van je concept', { exact: true })).toHaveAttribute('id', 'studio-title');
    await expect(page.getByLabel('Notitie', { exact: true })).toHaveAttribute('id', 'studio-note');
    await expect(page.locator('#studio-title')).toHaveAttribute('maxlength', '80');
    await expect(page.locator('#studio-note')).toHaveAttribute('maxlength', '2000');
    for (const id of ['studio-title-count', 'studio-note-count', 'studio-preview-title', 'studio-preview-note', 'studio-draft-state']) {
      assert.equal(await page.locator(`#${id}`).getAttribute('aria-live'), null);
      assert.notEqual(await page.locator(`#${id}`).getAttribute('role'), 'status');
    }
    await page.locator('#studio-title').focus();
    await page.keyboard.type('Een eerste gedachte');
    await preview(page, 'Een eerste gedachte', '');
    await expect(page.locator('#studio-title')).toBeFocused();
  });
});

test('live preview preserves literal text and counts the existing UTF-16 field limits', { timeout: 45_000 }, async t => {
  await presentation(t, async page => {
    const title = '<img src=x onerror="window.rioDraftInjected=true">';
    const note = '  Eerste regel\n\n\t<script>window.rioDraftInjected=true</script> & laatste regel.  ';
    await page.locator('#studio-title').fill(title);
    await page.locator('#studio-note').fill(note);
    await preview(page, title, note);
    assert.equal(await page.locator('#studio-preview-title img, #studio-preview-note script').count(), 0);
    assert.equal(await page.evaluate(() => window.rioDraftInjected), undefined);
    await expect(page.locator('#studio-preview-note')).toHaveCSS('white-space', 'pre-wrap');
    await page.locator('#studio-title').fill('😀');
    await page.locator('#studio-note').fill('e\u0301');
    await preview(page, '😀', 'e\u0301');
    const maximumTitle = '😀'.repeat(40);
    const maximumNote = '😀'.repeat(1000);
    await page.locator('#studio-title').fill(maximumTitle);
    await page.locator('#studio-note').fill(maximumNote);
    await preview(page, maximumTitle, maximumNote);
    assert.deepEqual(await exportedDraft(page), envelope(maximumTitle, maximumNote));
  });
});

test('clear and canonical import update the preview while rejected imports preserve it', { timeout: 45_000 }, async t => {
  await presentation(t, async page => {
    const title = '  Mijn concept  ';
    const note = '\n  Een lokale notitie.\nTweede regel.  ';
    await importDraft(page, envelope(title, note));
    await expect(page.locator('#studio-title')).toHaveValue(title);
    await preview(page, title, note);
    await expect(page.locator('#studio-feedback')).toBeFocused();
    assert.deepEqual(await exportedDraft(page), envelope(title, note));
    for (const invalid of [
      { ...envelope('Verboden', 'Wijziging'), authority: { ...AUTHORITY, consentGranted: true } },
      envelope('😀'.repeat(41), 'Te lange titel'),
      envelope('Te lange notitie', '😀'.repeat(1001)),
    ]) {
      await importDraft(page, invalid);
      await expect(page.locator('#studio-feedback')).toHaveText(IMPORT_ERROR);
      await expect(page.locator('#studio-title')).toHaveValue(title);
      await expect(page.locator('#studio-note')).toHaveValue(note);
      await preview(page, title, note);
    }
    assert.deepEqual(await exportedDraft(page), envelope(title, note));
    // Native text inputs strip title line breaks; textareas normalize CRLF to LF.
    // The existing export already reads those actual field values.
    await importDraft(page, envelope('a\nb', 'line1\r\nline2'));
    await expect(page.locator('#studio-title')).toHaveValue('ab');
    await expect(page.locator('#studio-note')).toHaveValue('line1\nline2');
    await preview(page, 'ab', 'line1\nline2');
    assert.deepEqual(await exportedDraft(page), envelope('ab', 'line1\nline2'));
    await page.locator('#studio-clear').click();
    await preview(page, '', '');
    await expect(page.locator('#studio-title')).toHaveValue('');
    await expect(page.locator('#studio-note')).toHaveValue('');
    await expect(page.locator('#studio-title')).toBeFocused();
  });
});

test('a stale asynchronous import cannot replace newer typed text or its preview', { timeout: 45_000 }, async t => {
  await presentation(t, async page => {
    await page.evaluate(() => {
      const original = File.prototype.text;
      File.prototype.text = function () {
        if (this.name !== 'delayed-draft.json') return original.call(this);
        return new Promise(resolve => { window.rioReleaseDraft = resolve; });
      };
    });
    await importDraft(page, envelope('Oud bestand', 'Oude inhoud'), 'delayed-draft.json');
    await page.waitForFunction(() => typeof window.rioReleaseDraft === 'function');
    await page.locator('#studio-title').fill('Nieuw getypt');
    await page.locator('#studio-note').fill('Deze tekst blijft lokaal.');
    await page.evaluate(async content => {
      window.rioReleaseDraft(content);
      await Promise.resolve();
      await Promise.resolve();
    }, JSON.stringify(envelope('Oud bestand', 'Oude inhoud')));
    await preview(page, 'Nieuw getypt', 'Deze tekst blijft lokaal.');
    assert.deepEqual(await exportedDraft(page), envelope('Nieuw getypt', 'Deze tekst blijft lokaal.'));
  });
});

test('local Studio and long previews reflow at desktop, Android and narrow widths', { timeout: 45_000 }, async t => {
  await presentation(t, async page => {
    await page.locator('#studio-title').fill('T'.repeat(80));
    await page.locator('#studio-note').fill('N'.repeat(2000));
    const paper = page.getByRole('region', { name: 'Leesvoorbeeld van je lokale concept', exact: true });
    await expect(paper).toHaveAttribute('tabindex', '0');
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await preview(page, 'T'.repeat(80), 'N'.repeat(2000));
      await paper.evaluate(element => { element.scrollTop = 0; });
      const dimensions = await paper.evaluate(element => ({
        height: element.getBoundingClientRect().height,
        clientHeight: element.clientHeight, scrollHeight: element.scrollHeight,
      }));
      assert.ok(dimensions.clientHeight <= 448 && dimensions.height <= 450);
      if (width === 320) assert.ok(dimensions.scrollHeight > dimensions.clientHeight);
      await paper.focus();
      await page.keyboard.press('PageDown');
      await expect(paper).toBeFocused();
      await expect(paper).toHaveCSS('outline-width', '3px');
      assert.notEqual(await paper.evaluate(element => getComputedStyle(element).outlineStyle), 'none');
      if (dimensions.scrollHeight > dimensions.clientHeight) {
        await expect.poll(() => paper.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
      }
      assert.deepEqual(await page.evaluate(() => {
        const root = document.documentElement;
        return {
          overflow: root.scrollWidth > root.clientWidth + 1,
          controlsOutside: [...document.querySelectorAll('input, textarea, button')].some(element => {
            if (!element.getClientRects().length) return false;
            const box = element.getBoundingClientRect();
            return box.left < -1 || box.right > root.clientWidth + 1;
          }),
        };
      }), { overflow: false, controlsOutside: false });
    }
  });
});
