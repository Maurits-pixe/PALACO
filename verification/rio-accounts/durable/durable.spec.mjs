import { test, expect } from '@playwright/test';
import { constants } from 'node:fs';
import { open, mkdir, lstat, readFile, unlink } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

const BFF = 'https://localhost:8088';
const ISSUER = 'http://127.0.0.1:8089/realms/rio-synthetic';
const SESSION_NAME = '__Host-rio_session';
const STATE_URL = new URL('../.runtime/durable-browser-state.json', import.meta.url);
const RUNTIME_URL = new URL('../.runtime/', import.meta.url);
const FIXTURE_PATH = fileURLToPath(new URL('../fixture.py', import.meta.url));
const runFile = promisify(execFile);
const EXPECTED = {
  alpha: { username: 'TST-alpha', subject: '11111111-1111-4111-8111-111111111111' },
  beta: { username: 'TST-beta', subject: '22222222-2222-4222-8222-222222222222' },
};
const ACCOUNT_NAMES = ['alpha', 'alphaPeer', 'beta'];
let credentials;

test.beforeAll(async () => {
  credentials = JSON.parse(await readFile(new URL('../.runtime/test-credentials.json', import.meta.url), 'utf8'));
  for (const name of ['alpha', 'beta']) {
    const actual = credentials[name];
    if (!actual || actual.username !== EXPECTED[name].username || actual.subject !== EXPECTED[name].subject ||
        typeof actual.password !== 'string' || actual.password.length < 24) {
      throw new Error('Synthetic runtime credential contract is invalid');
    }
  }
});

async function contextFor(browser) {
  return browser.newContext({
    ignoreHTTPSErrors: true, acceptDownloads: false, serviceWorkers: 'block',
  });
}

async function readMe(page) {
  return page.evaluate(async () => {
    const response = await fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' });
    return { status: response.status, data: response.ok ? await response.json() : null };
  });
}

async function ownAccount(page, username) {
  const response = await readMe(page);
  expect(response.status).toBe(200);
  const data = response.data;
  expect(Object.keys(data).sort()).toEqual([
    'account1', 'accountActive', 'accountId', 'actorKind', 'canOpenContact',
    'credentialControl', 'csrfToken', 'mode', 'operativeAuthority',
  ]);
  expect(data.accountId).toBe(username);
  expect(data.actorKind).toBe('SYNTHETIC_DEV_ACTOR');
  expect(data.credentialControl).toBe('VERIFIED_DEV_OIDC');
  expect(typeof data.csrfToken === 'string' && /^[A-Za-z0-9_-]{43}$/.test(data.csrfToken)).toBe(true);
  expect(data.mode).toBe('SYNTHETIC_ONLY');
  expect(data.accountActive).toBe(false);
  expect(data.canOpenContact).toBe(false);
  expect(data.operativeAuthority).toBe('NONE');
  expect(data.account1).toBe('HOLD');
  return data;
}

async function cookieFor(context, page) {
  const cookies = await context.cookies(BFF);
  const cookie = cookies.find(item => item.name === SESSION_NAME);
  expect(Boolean(cookie)).toBe(true);
  expect(cookie.secure).toBe(true);
  expect(cookie.httpOnly).toBe(true);
  expect(cookie.sameSite).toBe('Lax');
  expect(cookie.domain).toBe('localhost');
  expect(cookie.path).toBe('/');
  expect(/^[A-Za-z0-9_-]{43}$/.test(cookie.value)).toBe(true);
  expect(cookies.some(item => item.name === '__Host-rio_transaction')).toBe(false);
  const storage = await page.evaluate(() => ({
    local: localStorage.length,
    session: sessionStorage.length,
    visibleCookie: document.cookie.includes('__Host-rio_session='),
  }));
  expect(storage).toEqual({ local: 0, session: 0, visibleCookie: false });
  // Save only the RIO cookie, never Keycloak SSO cookies or full browser storage.
  // Session-cookie retention makes the server, rather than client Max-Age, decisive.
  return {
    name: SESSION_NAME, value: cookie.value, domain: 'localhost', path: '/',
    secure: true, httpOnly: true, sameSite: 'Lax', expires: -1,
  };
}

async function login(page, user) {
  await page.goto(BFF);
  expect((await readMe(page)).status).toBe(401);
  await page.locator('#start-login').click();
  await page.waitForURL(url => url.origin === 'http://127.0.0.1:8089' &&
    url.pathname === '/realms/rio-synthetic/protocol/openid-connect/auth');
  const query = new URL(page.url()).searchParams;
  expect(query.get('response_type')).toBe('code');
  expect(query.get('redirect_uri')).toBe(BFF + '/auth/callback');
  expect(query.get('client_id')).toBe('rio-bff');
  expect(query.get('scope')).toBe('openid');
  expect(query.get('code_challenge_method')).toBe('S256');
  expect(/^[A-Za-z0-9_-]{43}$/.test(query.get('code_challenge') ?? '')).toBe(true);
  expect((query.get('state') ?? '').length >= 32).toBe(true);
  expect((query.get('nonce') ?? '').length >= 32).toBe(true);
  expect(await page.locator('a[href*="/registrations"]').count()).toBe(0);
  await page.locator('input[name="username"]').fill(user.username);
  await page.locator('input[name="password"]').fill(user.password);
  await page.locator('#kc-login').click();
  await page.waitForURL(url => url.origin === BFF && url.pathname === '/');
  await expect(page.locator('#account-id')).toHaveText(user.username);
}

async function mutation(page, path, csrfToken) {
  return page.evaluate(async ({ path, csrfToken }) => {
    const response = await fetch(path, {
      method: 'POST', credentials: 'same-origin', headers: {
        'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken,
      }, body: '{}',
    });
    return response.status;
  }, { path, csrfToken });
}

async function controlFixture(command) {
  // Fixed subprocess arguments only; application runtime has no test-admin route.
  if (!['stop-db', 'start-db', 'restart-bff'].includes(command)) throw new Error('Unsupported fixture process operation');
  try {
    await runFile(process.platform === 'win32' ? 'python' : 'python3', [FIXTURE_PATH, command], {
      timeout: 15_000, maxBuffer: 64 * 1024, windowsHide: true,
    });
  } catch {
    // Child errors may include database credentials/configuration: never forward them.
    throw new Error('Synthetic process fixture operation failed');
  }
}

async function privateDirectory() {
  const path = fileURLToPath(RUNTIME_URL);
  await mkdir(path, { mode: 0o700 }).catch(error => {
    if (error.code !== 'EEXIST') throw new Error('Private browser state directory could not be created');
  });
  const info = await lstat(path);
  if (!info.isDirectory() || info.isSymbolicLink() ||
      (process.platform !== 'win32' && (info.mode & 0o077) !== 0)) {
    throw new Error('Private browser state directory contract is invalid');
  }
}

async function saveState(accounts) {
  await privateDirectory();
  const handle = await open(STATE_URL, 'wx', 0o600);
  try {
    await handle.writeFile(JSON.stringify({
      schema: 'rio-durable-browser-private/v1', accounts,
    }) + '\n');
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function loadState() {
  await privateDirectory();
  const handle = await open(STATE_URL, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  let state;
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size > 8192 ||
        (process.platform !== 'win32' && (info.mode & 0o077) !== 0)) {
      throw new Error('Private browser state file contract is invalid');
    }
    state = JSON.parse(await handle.readFile('utf8'));
  } finally {
    await handle.close();
  }
  if (!state || state.schema !== 'rio-durable-browser-private/v1' ||
      JSON.stringify(Object.keys(state.accounts ?? {}).sort()) !== JSON.stringify([...ACCOUNT_NAMES].sort())) {
    throw new Error('Private durable browser state contract is invalid');
  }
  for (const name of ACCOUNT_NAMES) {
    const item = state.accounts[name];
    const cookie = item?.cookie;
    if (!cookie || cookie.name !== SESSION_NAME || cookie.domain !== 'localhost' ||
        cookie.path !== '/' || cookie.secure !== true || cookie.httpOnly !== true ||
        cookie.sameSite !== 'Lax' || cookie.expires !== -1 ||
        typeof cookie.value !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(cookie.value) ||
        typeof item.csrfToken !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(item.csrfToken)) {
      throw new Error('Saved synthetic session contract is invalid');
    }
  }
  return state.accounts;
}

async function restore(browser, saved) {
  const result = {};
  try {
    for (const name of ACCOUNT_NAMES) {
      const context = await contextFor(browser);
      const page = await context.newPage();
      result[name] = { context, page };
      await context.addCookies([saved[name].cookie]);
      await page.goto(BFF);
    }
    return result;
  } catch (error) {
    await closeContexts(result);
    throw error;
  }
}

async function closeContexts(contexts) {
  await Promise.all(Object.values(contexts).map(({ context }) => context.close()));
}

test('[RIO-DURABLE-01] Save actual OIDC sessions privately before BFF restart', async ({ browser }) => {
  const contexts = {};
  const saved = {};
  try {
    await test.step('durable-real-login', async () => {
      for (const name of ACCOUNT_NAMES) {
        const context = await contextFor(browser);
        const page = await context.newPage();
        contexts[name] = { context, page };
        await login(page, credentials[name === 'beta' ? 'beta' : 'alpha']);
      }
    });
    await test.step('durable-private-state', async () => {
      // Read all three again just before the restart to refresh their fixed idle budget.
      for (const name of ACCOUNT_NAMES) {
        const { context, page } = contexts[name];
        const account = await ownAccount(page, EXPECTED[name === 'beta' ? 'beta' : 'alpha'].username);
        saved[name] = { cookie: await cookieFor(context, page), csrfToken: account.csrfToken };
      }
      expect(new Set(ACCOUNT_NAMES.map(name => saved[name].cookie.value)).size).toBe(3);
      expect(new Set(ACCOUNT_NAMES.map(name => saved[name].csrfToken)).size).toBe(3);
      await saveState(saved);
    });
  } finally {
    await closeContexts(contexts);
  }
});

test('[RIO-DURABLE-02] Database outage denies access until controlled BFF recovery', async ({ browser }) => {
  const context = await contextFor(browser);
  let databaseMayBeStopped = false;
  try {
    const page = await context.newPage();
    await login(page, credentials.alpha);
    const before = await ownAccount(page, EXPECTED.alpha.username);
    const cookie = await cookieFor(context, page);
    await test.step('durable-database-outage', async () => {
      databaseMayBeStopped = true;
      await controlFixture('stop-db');
      expect((await readMe(page)).status).toBe(503);
      const loginStatus = await page.evaluate(async () => {
        const response = await fetch('/auth/start', {
          credentials: 'same-origin', redirect: 'manual', cache: 'no-store',
        });
        return response.status;
      });
      expect(loginStatus).toBe(503);
    });
    await controlFixture('start-db');
    databaseMayBeStopped = false;
    await test.step('durable-connection-stays-closed', async () => {
      // An uncertain connection stays poisoned even after PostgreSQL is ready again.
      expect((await readMe(page)).status).toBe(503);
    });
    await test.step('durable-database-recovery', async () => {
      await controlFixture('restart-bff');
      // Retain the original browser credential: recovery must not require a new login.
      await context.addCookies([cookie]);
      const after = await ownAccount(page, EXPECTED.alpha.username);
      expect(after.csrfToken === before.csrfToken).toBe(true);
      expect((await cookieFor(context, page)).value === cookie.value).toBe(true);
    });
  } finally {
    try {
      if (databaseMayBeStopped) await controlFixture('start-db');
    } finally {
      await context.close();
    }
  }
});

test('[RIO-DURABLE-03] Restart preserves own sessions and actor-scoped revocation', async ({ browser }) => {
  const saved = await loadState();
  const contexts = await restore(browser, saved);
  try {
    await test.step('durable-restart-access', async () => {
      for (const name of ACCOUNT_NAMES) {
        const { context, page } = contexts[name];
        const account = await ownAccount(page, EXPECTED[name === 'beta' ? 'beta' : 'alpha'].username);
        await expect(page.locator('#account-id')).toHaveText(account.accountId);
        expect(account.csrfToken === saved[name].csrfToken).toBe(true);
        expect((await cookieFor(context, page)).value === saved[name].cookie.value).toBe(true);
      }
    });
    await test.step('durable-cross-actor-csrf', async () => {
      expect(await mutation(contexts.alpha.page, '/auth/logout-all', saved.beta.csrfToken)).toBe(403);
      expect(await mutation(contexts.beta.page, '/auth/logout', saved.alpha.csrfToken)).toBe(403);
      expect(await mutation(contexts.alphaPeer.page, '/auth/logout', saved.alpha.csrfToken)).toBe(403);
      for (const name of ACCOUNT_NAMES) {
        await ownAccount(contexts[name].page, EXPECTED[name === 'beta' ? 'beta' : 'alpha'].username);
      }
    });
    await test.step('durable-native-revocation', async () => {
      const page = contexts.alpha.page;
      const [response] = await Promise.all([
        page.waitForResponse(response => response.url() === BFF + '/auth/logout-all' &&
          response.request().method() === 'POST', { timeout: 10_000 }),
        page.locator('#logout-all').click({ timeout: 10_000 }),
      ]);
      expect(response.status()).toBe(200);
      // The client must consume and validate the real logout JSON envelope
      // before it renders this success message. Observing the native UI and
      // the server-side revoked session avoids a Playwright response-body
      // lifecycle race; the closed-account invariants below remain mandatory.
      await expect(page.locator('#feedback')).toHaveText(
        'Lokale testsessie afgemeld. De identity-provider heeft een afzonderlijke sessie.'
      );
      await expect(page.locator('#start-login')).toBeVisible();
      expect((await readMe(page)).status).toBe(401);
      expect((await contexts.alpha.context.cookies(BFF)).some(cookie => cookie.name === SESSION_NAME)).toBe(false);
      // Explicitly replay saved cookies; deleted browser cookies alone prove little.
      for (const name of ['alpha', 'alphaPeer']) {
        await contexts[name].context.addCookies([saved[name].cookie]);
        expect((await readMe(contexts[name].page)).status).toBe(401);
      }
      await ownAccount(contexts.beta.page, EXPECTED.beta.username);
    });
  } finally {
    await closeContexts(contexts);
  }
});

test('[RIO-DURABLE-04] Saved revoked cookies stay denied after another BFF restart', async ({ browser }) => {
  const saved = await loadState();
  const contexts = await restore(browser, saved);
  try {
    await test.step('durable-revocation-after-restart', async () => {
      for (const name of ['alpha', 'alphaPeer']) {
        const { context, page } = contexts[name];
        // Contexts contain the retained cookie while the durable server still denies it.
        expect((await context.cookies(BFF)).some(cookie =>
          cookie.name === SESSION_NAME && cookie.value === saved[name].cookie.value)).toBe(true);
        expect((await readMe(page)).status).toBe(401);
        await expect(page.locator('#start-login')).toBeVisible();
        await expect(page.locator('#account-id')).toBeHidden();
        await expect(page.locator('#account-id')).toHaveText('');
      }
    });
    await test.step('durable-unaffected-actor', async () => {
      const account = await ownAccount(contexts.beta.page, EXPECTED.beta.username);
      expect(account.csrfToken === saved.beta.csrfToken).toBe(true);
      expect((await cookieFor(contexts.beta.context, contexts.beta.page)).value === saved.beta.cookie.value).toBe(true);
    });
  } finally {
    try {
      await closeContexts(contexts);
    } finally {
      await unlink(STATE_URL);
    }
  }
});
