import { test, expect, devices } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

export const BFF = 'https://localhost:8088';
export const SCOPE = 'RIO_SYNTHETIC_SESSION_TEST_V1';
const SESSION = '__Host-rio_session';
const execute = promisify(execFile);
const FIXTURE = fileURLToPath(new URL('../fixture.py', import.meta.url));
let privateUsers;

export async function users() {
  if (!privateUsers) {
    privateUsers = JSON.parse(await readFile(new URL('../.runtime/test-credentials.json', import.meta.url), 'utf8'));
    for (const [name, subject] of [
      ['alpha', '11111111-1111-4111-8111-111111111111'],
      ['beta', '22222222-2222-4222-8222-222222222222'],
    ]) {
      const user = privateUsers[name];
      if (user?.username !== 'TST-' + name || user?.subject !== subject ||
          typeof user.password !== 'string' || user.password.length < 24) {
        throw new Error('Synthetic runtime credential contract is invalid');
      }
    }
  }
  return privateUsers;
}

export function isAndroid(testInfo) { return testInfo.project.name === 'android-emulation'; }

export async function contextFor(browser, testInfo) {
  const android = isAndroid(testInfo);
  return browser.newContext({
    ...(android ? devices['Pixel 7'] : devices['Desktop Chrome']),
    viewport: android ? { width: 390, height: 844 } : { width: 1440, height: 900 },
    ignoreHTTPSErrors: true, acceptDownloads: true, serviceWorkers: 'block',
  });
}

export async function activate(page, locator, testInfo) {
  if (isAndroid(testInfo)) await locator.tap();
  else {
    await locator.focus();
    await page.keyboard.press('Enter');
  }
}

export async function chooseConsent(page, testInfo) {
  const choice = page.locator('#consent-choice');
  await expect(choice).not.toBeChecked();
  if (isAndroid(testInfo)) await choice.tap();
  else {
    await choice.focus();
    await page.keyboard.press('Space');
  }
  await expect(choice).toBeChecked();
}

export async function login(page, user, testInfo) {
  await page.context().clearCookies({ domain: '127.0.0.1' });
  await page.goto(BFF);
  await expect(page.locator('#start-login')).toBeVisible();
  await activate(page, page.locator('#start-login'), testInfo);
  await page.waitForURL(url => url.origin === 'http://127.0.0.1:8089' &&
    url.pathname === '/realms/rio-synthetic/protocol/openid-connect/auth');
  const query = new URL(page.url()).searchParams;
  expect(query.get('response_type')).toBe('code');
  expect(query.get('redirect_uri')).toBe(BFF + '/auth/callback');
  expect(query.get('client_id')).toBe('rio-bff');
  expect(query.get('scope')).toBe('openid');
  expect(query.get('code_challenge_method')).toBe('S256');
  await page.locator('input[name="username"]').fill(user.username);
  await page.locator('input[name="password"]').fill(user.password);
  await activate(page, page.locator('#kc-login'), testInfo);
  await page.waitForURL(url => url.origin === BFF && url.pathname === '/');
  await expect(page.locator('#account-id')).toHaveText(user.username);
  await expect(page.locator('#consent-refresh')).toBeEnabled();
}

export async function me(page) {
  return page.evaluate(async () => {
    const response = await fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' });
    return { status: response.status, data: response.ok ? await response.json() : null };
  });
}

export async function consent(page) {
  return page.evaluate(async () => {
    const response = await fetch('/api/consent', { credentials: 'same-origin', cache: 'no-store' });
    return { status: response.status, data: response.ok ? await response.json() : null };
  });
}

export async function writeConsent(page, body, csrfToken) {
  return page.evaluate(async ({ body, csrfToken }) => {
    const response = await fetch('/api/consent', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify(body),
    });
    return { status: response.status, data: response.ok ? await response.json() : null };
  }, { body, csrfToken });
}

export function receiptFrom(response) {
  expect(response.status).toBe(200);
  const envelope = response.data;
  expect(Object.keys(envelope).sort()).toEqual([
    'account1', 'accountActive', 'canOpenContact', 'mode', 'operativeAuthority', 'receipt',
  ]);
  expect(envelope.mode).toBe('SYNTHETIC_ONLY');
  expect(envelope.account1).toBe('HOLD');
  expect(envelope.accountActive).toBe(false);
  expect(envelope.canOpenContact).toBe(false);
  expect(envelope.operativeAuthority).toBe('NONE');
  const receipt = envelope.receipt;
  expect(Object.keys(receipt).sort()).toEqual(['expiresAt', 'granted', 'revision', 'scope']);
  expect(receipt.scope).toBe(SCOPE);
  expect(typeof receipt.granted).toBe('boolean');
  expect(Number.isSafeInteger(receipt.revision) && receipt.revision >= 0).toBe(true);
  expect(receipt.granted
    ? Number.isSafeInteger(receipt.expiresAt) && receipt.expiresAt > 0
    : receipt.expiresAt === null).toBe(true);
  return receipt;
}

export async function nativeConsent(page, button, testInfo) {
  const [response] = await Promise.all([
    page.waitForResponse(response => response.url() === BFF + '/api/consent' &&
      response.request().method() === 'POST', { timeout: 10_000 }),
    activate(page, page.locator(button), testInfo),
  ]);
  // A native POST is complete only when the server has committed the choice.
  // Verify its actual durable receipt through the browser context's shared
  // cookie jar, not an ephemeral page.evaluate() execution context: that may
  // disappear while Chromium settles a keyboard/touch interaction. This GET
  // cannot grant consent and must remain bound to the original actor session.
  const status = response.status();
  if (!response.ok()) return { status, data: null };
  const readback = await page.context().request.get(BFF + '/api/consent', {
    timeout: 8000, maxRedirects: 0, failOnStatusCode: false,
  });
  try {
    expect(readback.status()).toBe(200);
    expect((readback.headers()['content-type'] || '').split(';')[0].trim().toLowerCase())
      .toBe('application/json');
    const bytes = await readback.body();
    expect(bytes.byteLength).toBeLessThanOrEqual(16384);
    const data = JSON.parse(bytes.toString('utf8'));
    receiptFrom({ status: 200, data });
    return { status, data };
  } finally {
    await readback.dispose();
  }
}

export async function retainCookie(context) {
  const session = (await context.cookies(BFF)).find(cookie => cookie.name === SESSION);
  expect(Boolean(session)).toBe(true);
  expect(session.secure && session.httpOnly && session.domain === 'localhost').toBe(true);
  expect(session.sameSite).toBe('Lax');
  expect(session.path).toBe('/');
  await context.addCookies([{ ...session, expires: -1 }]);
  return session;
}

export async function noPersistentState(page) {
  const observed = await page.evaluate(async () => ({
    local: localStorage.length,
    session: sessionStorage.length,
    databases: (await indexedDB.databases()).length,
    caches: (await caches.keys()).length,
    visibleSession: document.cookie.includes('__Host-rio_session='),
  }));
  expect(observed).toEqual({ local: 0, session: 0, databases: 0, caches: 0, visibleSession: false });
}

export async function noOverflow(page) {
  const observed = await page.evaluate(() => {
    const root = document.documentElement;
    const controls = [...document.querySelectorAll('button,input,textarea,a')].filter(element =>
      element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden');
    return {
      overflow: root.scrollWidth > root.clientWidth + 1,
      controlsOutside: controls.some(element => {
        const box = element.getBoundingClientRect();
        return box.left < -1 || box.right > root.clientWidth + 1;
      }),
    };
  });
  expect(observed).toEqual({ overflow: false, controlsOutside: false });
}

export function observeWrites(page) {
  const record = { count: 0 };
  const listener = request => {
    if (!['GET', 'HEAD'].includes(request.method())) record.count += 1;
  };
  page.on('request', listener);
  return { record, stop: () => page.off('request', listener) };
}

export async function downloadDraft(page, testInfo) {
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    activate(page, page.locator('#studio-export'), testInfo),
  ]);
  try {
    expect(download.suggestedFilename()).toBe('rio-lokaal-concept.json');
    expect(await download.failure()).toBe(null);
    const stream = await download.createReadStream();
    const chunks = [];
    let size = 0;
    for await (const chunk of stream) {
      size += chunk.length;
      if (size > 12288) throw new Error('Local draft download exceeded its public size contract');
      chunks.push(chunk);
    }
    const bytes = Buffer.concat(chunks);
    return { bytes, text: bytes.toString('utf8'), value: JSON.parse(bytes.toString('utf8')) };
  } finally {
    await download.delete();
  }
}

export async function controlFixture(command) {
  if (!['stop-db', 'start-db', 'restart-bff'].includes(command)) {
    throw new Error('Unsupported synthetic fixture operation');
  }
  try {
    await execute(process.platform === 'win32' ? 'python' : 'python3', [FIXTURE, command], {
      timeout: 15_000, maxBuffer: 64 * 1024, windowsHide: true,
    });
  } catch {
    throw new Error('Synthetic fixture operation failed');
  }
}
