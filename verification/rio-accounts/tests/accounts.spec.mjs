import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const BFF = 'https://localhost:8088';
const ISSUER = 'http://127.0.0.1:8089/realms/rio-synthetic';
const SESSION_NAME = '__Host-rio_session';
const EXPECTED_USERS = {
  alpha: { username: 'TST-alpha', subject: '11111111-1111-4111-8111-111111111111' },
  beta: { username: 'TST-beta', subject: '22222222-2222-4222-8222-222222222222' },
};
let credentials;
const pageErrorCounts = new WeakMap();

test.beforeAll(async () => {
  credentials = JSON.parse(await readFile(new URL('../.runtime/test-credentials.json', import.meta.url), 'utf8'));
  for (const name of ['alpha', 'beta']) {
    const user = credentials[name];
    if (!user || user.username !== EXPECTED_USERS[name].username ||
        user.subject !== EXPECTED_USERS[name].subject ||
        typeof user.password !== 'string' || user.password.length < 24) {
      throw new Error('Synthetic runtime credential contract is invalid');
    }
  }
});

async function contextFor(browser) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    acceptDownloads: false,
    serviceWorkers: 'block',
  });
  context.on('page', page => {
    const counter = { count: 0 };
    pageErrorCounts.set(page, counter);
    page.on('pageerror', () => { counter.count += 1; });
  });
  return context;
}

async function clickLogoutWithObservation(page, testInfo) {
  const observation = {
    logoutRequests: 0, logoutResponses: 0, logoutFailedRequests: 0,
    otherBffPosts: 0, logoutStatuses: [], pageErrors: 0,
    logoutButtonVisibleBefore: false, logoutButtonEnabledBefore: false,
    logoutButtonVisibleAfter: false, clickCompleted: false,
    responseMatched: false, feedbackBucket: 'unavailable',
  };
  const isLogout = request => {
    try {
      const url = new URL(request.url());
      return url.origin === BFF && url.pathname === '/auth/logout' && request.method() === 'POST';
    } catch { return false; }
  };
  const onRequest = request => {
    if (isLogout(request)) observation.logoutRequests += 1;
    else {
      try {
        if (new URL(request.url()).origin === BFF && request.method() === 'POST') observation.otherBffPosts += 1;
      } catch {}
    }
  };
  const onResponse = response => {
    if (isLogout(response.request())) {
      observation.logoutResponses += 1;
      if (observation.logoutStatuses.length < 16) observation.logoutStatuses.push(response.status());
    }
  };
  const onFailedRequest = request => {
    if (isLogout(request)) observation.logoutFailedRequests += 1;
  };
  page.on('request', onRequest);
  page.on('response', onResponse);
  page.on('requestfailed', onFailedRequest);
  try {
    observation.logoutButtonVisibleBefore = await page.locator('#logout').isVisible();
    observation.logoutButtonEnabledBefore = await page.locator('#logout').isEnabled({ timeout: 1000 });
    const [response] = await Promise.all([
      page.waitForResponse(response => response.url() === BFF + '/auth/logout' &&
        response.request().method() === 'POST', { timeout: 10_000 }),
      page.locator('#logout').click({ timeout: 10_000 }).then(() => { observation.clickCompleted = true; }),
    ]);
    observation.responseMatched = true;
    return response;
  } finally {
    page.off('request', onRequest);
    page.off('response', onResponse);
    page.off('requestfailed', onFailedRequest);
    observation.pageErrors = pageErrorCounts.get(page)?.count ?? 0;
    observation.logoutButtonVisibleAfter = await page.locator('#logout').isVisible().catch(() => false);
    const feedback = await page.locator('#feedback').textContent({ timeout: 1000 }).catch(() => null);
    observation.feedbackBucket = feedback === null ? 'unavailable' :
      feedback === '' ? 'empty' :
      feedback === 'Afmelden is niet gelukt.' ? 'logout_failed' :
      feedback === 'De testsessie kon niet worden gelezen.' ? 'read_failed' :
      feedback === 'Lokale testsessie afgemeld. De identity-provider heeft een afzonderlijke sessie.' ? 'logged_out' : 'other';
    testInfo.annotations.push({ type: 'rio-logout-observation', description: JSON.stringify(observation) });
  }
}

async function readMe(page) {
  return page.evaluate(async () => {
    const response = await fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' });
    return {
      status: response.status,
      data: response.ok ? await response.json() : null,
      cacheControl: response.headers.get('cache-control'),
    };
  });
}

async function mutate(page, path, { method = 'POST', csrfToken } = {}) {
  return page.evaluate(async ({ path, method, csrfToken }) => {
    const headers = method === 'POST' ? { 'Content-Type': 'application/json' } : {};
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    const response = await fetch(path, {
      method, credentials: 'same-origin', redirect: 'manual', headers,
      ...(method === 'POST' ? { body: '{}' } : {}),
    });
    return response.status;
  }, { path, method, csrfToken });
}

async function assertOwnAccount(page, username) {
  return test.step('own-account', async () => {
    const me = await readMe(page);
    expect(me.status).toBe(200);
    expect(me.data.accountId).toBe(username);
    expect(me.data.actorKind).toBe('SYNTHETIC_DEV_ACTOR');
    expect(me.data.credentialControl).toBe('VERIFIED_DEV_OIDC');
    expect(Object.keys(me.data).sort()).toEqual([
      'account1', 'accountActive', 'accountId', 'actorKind', 'canOpenContact',
      'credentialControl', 'csrfToken', 'mode', 'operativeAuthority',
    ]);
    expect(typeof me.data.csrfToken === 'string' && me.data.csrfToken.length >= 32).toBe(true);
    await test.step('hold-status', async () => {
      expect(me.data.accountActive).toBe(false);
      expect(me.data.mode).toBe('SYNTHETIC_ONLY');
      expect(me.data.operativeAuthority).toBe('NONE');
      expect(me.data.canOpenContact).toBe(false);
      expect(me.data.account1).toBe('HOLD');
    });
    return me.data;
  });
}

async function assertCookie(context, page) {
  return test.step('cookie-contract', async () => {
    const cookies = await context.cookies(BFF);
    const session = cookies.find(cookie => cookie.name === SESSION_NAME);
    expect(Boolean(session)).toBe(true);
    expect(session.secure).toBe(true);
    expect(session.httpOnly).toBe(true);
    expect(session.sameSite).toBe('Lax');
    expect(session.domain).toBe('localhost');
    expect(session.path).toBe('/');
    expect(session.value.length >= 32 && !session.value.includes('.')).toBe(true);
    expect(cookies.some(cookie => cookie.name === '__Host-rio_transaction')).toBe(false);
    await test.step('no-browser-tokens', async () => {
      const storage = await page.evaluate(() => ({
        local: localStorage.length,
        session: sessionStorage.length,
        visibleSession: document.cookie.includes('__Host-rio_session='),
      }));
      expect(storage).toEqual({ local: 0, session: 0, visibleSession: false });
      const body = await page.textContent('body');
      expect(/access_token|id_token|refresh_token|client_secret/.test(body)).toBe(false);
    });
    return session;
  });
}

async function beginLogin(page, { rotate = false } = {}) {
  await page.goto(BFF);
  await test.step('initial-access', async () => {
    expect((await readMe(page)).status).toBe(rotate ? 200 : 401);
    if (!rotate) await expect(page.locator('#start-login')).toBeVisible();
  });
  if (rotate) await page.goto(BFF + '/auth/start');
  else await page.locator('#start-login').click();
  await page.waitForURL(url => url.origin === 'http://127.0.0.1:8089' &&
    url.pathname === '/realms/rio-synthetic/protocol/openid-connect/auth');
  return test.step('authorization-contract', async () => {
    const url = new URL(page.url());
    const query = url.searchParams;
    expect(query.get('response_type')).toBe('code');
    expect(query.get('client_id')).toBe('rio-bff');
    expect(query.get('redirect_uri')).toBe(BFF + '/auth/callback');
    expect(query.get('code_challenge_method')).toBe('S256');
    expect(/^[A-Za-z0-9_-]{43}$/.test(query.get('code_challenge') ?? '')).toBe(true);
    expect((query.get('state') ?? '').length >= 32).toBe(true);
    expect((query.get('nonce') ?? '').length >= 32).toBe(true);
    const scopes = (query.get('scope') ?? '').split(' ').filter(Boolean).sort();
    expect(scopes).toEqual(['openid']);
    expect(await page.locator('a[href*="/registrations"]').count()).toBe(0);
    await expect(page.locator('input[name="username"]')).toBeVisible();
    return { state: query.get('state'), nonce: query.get('nonce'), challenge: query.get('code_challenge') };
  });
}

async function login(page, user, { rotate = false } = {}) {
  // Force the explicit real credential form without altering BFF or peer sessions.
  await page.context().clearCookies({ domain: '127.0.0.1' });
  let browserExchangedTokens = false;
  const observe = request => {
    if (request.url().startsWith(ISSUER + '/protocol/openid-connect/token')) {
      browserExchangedTokens = true;
    }
  };
  page.on('request', observe);
  try {
    const authorization = await beginLogin(page, { rotate });
    if (rotate) {
      // Starting reauthentication retains the current session until callback success.
      const retainedSessionPage = await page.context().newPage();
      try {
        await retainedSessionPage.goto(BFF);
        await assertOwnAccount(retainedSessionPage, user.username);
      } finally {
        await retainedSessionPage.close();
      }
    }
    await test.step('real-idp-login', async () => {
      await page.locator('input[name="username"]').fill(user.username);
      await page.locator('input[name="password"]').fill(user.password);
      await page.locator('#kc-login').click();
      await page.waitForURL(url => url.origin === BFF && url.pathname === '/');
      await expect(page.locator('#account-id')).toHaveText(user.username);
    });
    await test.step('no-browser-tokens', async () => {
      expect(browserExchangedTokens).toBe(false);
    });
    return authorization;
  } finally {
    page.off('request', observe);
  }
}

test('[RIO-E2E-01] Two real users have separate sessions and account data', async ({ browser }) => {
  const alpha = await contextFor(browser);
  const beta = await contextFor(browser);
  try {
    const alphaPage = await alpha.newPage();
    const betaPage = await beta.newPage();
    const alphaAuth = await login(alphaPage, credentials.alpha);
    const betaAuth = await login(betaPage, credentials.beta);
    const alphaAccount = await assertOwnAccount(alphaPage, credentials.alpha.username);
    const betaAccount = await assertOwnAccount(betaPage, credentials.beta.username);
    const alphaCookie = await assertCookie(alpha, alphaPage);
    const betaCookie = await assertCookie(beta, betaPage);
    if (process.env.RIO_CMV_HTTP_PROOF === '1') {
      await test.step('cmv-objects', async () => {
        const objectId = await alphaPage.evaluate(() => {
          const bytes = crypto.getRandomValues(new Uint8Array(32));
          return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        });
        const request = async (page, method, path, csrf, body) => page.evaluate(async args => {
          const headers = args.csrf ? {'content-type':'application/json','x-csrf-token':args.csrf} : {};
          const response = await fetch(args.path, {method:args.method,headers,
            credentials:'same-origin',cache:'no-store',...(args.body ? {body:JSON.stringify(args.body)} : {})});
          const data = response.ok ? await response.json() : null;
          return {status:response.status, noStore:response.headers.get('cache-control')==='no-store',
            closed:data ? data.accountActive===false && data.canOpenContact===false && data.operativeAuthority==='NONE' : true,
            payloadMatches:data?.object?.payload==='YnJvd3NlciBmaXh0dXJl',
            catalogHasObject:data?.objects?.some(item=>item.objectId===args.objectId) ?? false,
            catalogState:data?.objects?.find(item=>item.objectId===args.objectId)?.state ?? null,
            catalogNoPayload:Array.isArray(data?.objects) && data.objects.every(item=>!Object.hasOwn(item,'payload'))};
        }, {method,path,csrf,body,objectId});
        const body={objectId,payload:'YnJvd3NlciBmaXh0dXJl',retentionMs:60000};
        const path='/api/storage/objects/'+objectId;
        expect((await request(alphaPage,'POST','/api/storage/objects',betaAccount.csrfToken,body)).status).toBe(403);
        const created=await request(alphaPage,'POST','/api/storage/objects',alphaAccount.csrfToken,body);
        expect(created.status).toBe(201); expect(created.noStore && created.closed).toBe(true);
        const ownCatalog=await request(alphaPage,'GET','/api/storage/objects',null,null);
        expect(ownCatalog.status).toBe(200);expect(ownCatalog.catalogHasObject && ownCatalog.catalogNoPayload).toBe(true);
        expect(ownCatalog.catalogState).toBe('LIVE');
        const foreignCatalog=await request(betaPage,'GET','/api/storage/objects',null,null);
        expect(foreignCatalog.status).toBe(200);expect(foreignCatalog.catalogHasObject).toBe(false);
        const own=await request(alphaPage,'GET',path,null,null);
        expect(own.status).toBe(200); expect(own.payloadMatches && own.noStore && own.closed).toBe(true);
        expect((await request(betaPage,'GET',path,null,null)).status).toBe(403);
        expect((await request(betaPage,'DELETE',path,betaAccount.csrfToken,{})).status).toBe(403);
        expect((await request(alphaPage,'POST','/api/storage/objects',alphaAccount.csrfToken,body)).status).toBe(409);
        expect((await request(alphaPage,'DELETE',path,alphaAccount.csrfToken,{})).status).toBe(200);
        const deletedCatalog=await request(alphaPage,'GET','/api/storage/objects',null,null);
        expect(deletedCatalog.catalogState).toBe('DELETED');expect(deletedCatalog.catalogNoPayload).toBe(true);
        expect((await request(alphaPage,'GET',path,null,null)).status).toBe(403);
        expect((await request(alphaPage,'POST','/api/storage/objects',alphaAccount.csrfToken,body)).status).toBe(409);
        expect((await request(betaPage,'GET','/api/storage/usage',null,null)).status).toBe(200);
      });
    }
    await test.step('context-isolation', async () => {
      expect(alphaCookie.value !== betaCookie.value).toBe(true);
      expect(alphaAccount.csrfToken !== betaAccount.csrfToken).toBe(true);
      expect(alphaAuth.state !== betaAuth.state).toBe(true);
      expect(alphaAuth.nonce !== betaAuth.nonce).toBe(true);
      expect(alphaAuth.challenge !== betaAuth.challenge).toBe(true);
      expect(await mutate(alphaPage, '/auth/logout', { csrfToken: betaAccount.csrfToken })).toBe(403);
      expect(await mutate(betaPage, '/auth/logout-all', { csrfToken: alphaAccount.csrfToken })).toBe(403);
      await assertOwnAccount(alphaPage, credentials.alpha.username);
      await assertOwnAccount(betaPage, credentials.beta.username);
    });
    await test.step('session-rotation', async () => {
      await login(alphaPage, credentials.alpha, { rotate: true });
      const replacementCookie = await assertCookie(alpha, alphaPage);
      expect(replacementCookie.value !== alphaCookie.value).toBe(true);
      await alpha.addCookies([{ ...alphaCookie, expires: -1 }]);
      expect((await readMe(alphaPage)).status).toBe(401);
      await alpha.addCookies([replacementCookie]);
      await assertOwnAccount(alphaPage, credentials.alpha.username);
      await assertOwnAccount(betaPage, credentials.beta.username);
    });
  } finally {
    await Promise.all([alpha.close(), beta.close()]);
  }
});

test('[RIO-E2E-02] Unauthenticated and invalid sessions fail closed', async ({ browser }) => {
  const context = await contextFor(browser);
  try {
    const page = await context.newPage();
    await page.goto(BFF);
    await test.step('initial-access', async () => {
      expect((await readMe(page)).status).toBe(401);
      await expect(page.locator('#account-id')).toBeHidden();
      await expect(page.locator('#account-id')).toHaveText('');
    });
    await test.step('invalid-session', async () => {
      await context.addCookies([{
        name: SESSION_NAME, value: 'A'.repeat(43),
        domain: 'localhost', path: '/', secure: true, httpOnly: true, sameSite: 'Lax',
      }]);
      expect((await readMe(page)).status).toBe(401);
      await page.reload();
      await expect(page.locator('#start-login')).toBeVisible();
      await expect(page.locator('#account-id')).toBeHidden();
      await expect(page.locator('#account-id')).toHaveText('');
    });
  } finally {
    await context.close();
  }
});

test('[RIO-E2E-03] Invalid credentials create no BFF session', async ({ browser }) => {
  const context = await contextFor(browser);
  try {
    const page = await context.newPage();
    await beginLogin(page);
    await test.step('invalid-credentials', async () => {
      await page.locator('input[name="username"]').fill(credentials.alpha.username);
      await page.locator('input[name="password"]').fill('invalid-synthetic-password-' + Date.now());
      await page.locator('#kc-login').click();
      await expect(page.locator('#input-error, #input-error-username')).toBeVisible();
      expect(new URL(page.url()).origin).toBe('http://127.0.0.1:8089');
      expect((await context.cookies(BFF)).some(cookie => cookie.name === SESSION_NAME)).toBe(false);
      await page.goto(BFF);
      expect((await readMe(page)).status).toBe(401);
      await expect(page.locator('#account-id')).toBeHidden();
      await expect(page.locator('#account-id')).toHaveText('');
    });
  } finally {
    await context.close();
  }
});

test('[RIO-E2E-04] Logout invalidates the session without affecting another user', async ({ browser }, testInfo) => {
  const alpha = await contextFor(browser);
  const alphaPeer = await contextFor(browser);
  const beta = await contextFor(browser);
  try {
    const alphaPage = await alpha.newPage();
    const betaPage = await beta.newPage();
    await login(alphaPage, credentials.alpha);
    await login(betaPage, credentials.beta);
    await assertOwnAccount(alphaPage, credentials.alpha.username);
    const retiredCookie = await assertCookie(alpha, alphaPage);
    await test.step('logout-csrf', async () => {
      expect(await mutate(alphaPage, '/auth/logout', { method: 'GET' })).toBe(405);
      expect(await mutate(alphaPage, '/auth/logout-all', { method: 'GET' })).toBe(405);
      expect(await mutate(alphaPage, '/auth/logout')).toBe(403);
      expect(await mutate(alphaPage, '/auth/logout-all')).toBe(403);
      await assertOwnAccount(alphaPage, credentials.alpha.username);
    });
    await test.step('logout', async () => {
      const idpCookiesBefore = (await alpha.cookies(ISSUER + '/protocol/openid-connect/auth'))
        .filter(cookie => cookie.name.startsWith('KEYCLOAK_'))
        .map(({ name, value }) => [name, value]).sort();
      let providerLogoutRequested = false;
      const observeLogout = request => {
        if (request.url().startsWith(ISSUER + '/protocol/openid-connect/logout')) {
          providerLogoutRequested = true;
        }
      };
      alphaPage.on('request', observeLogout);
      const logoutResponse = await clickLogoutWithObservation(alphaPage, testInfo);
      alphaPage.off('request', observeLogout);
      expect(await logoutResponse.json()).toEqual({
        loggedOut: true, providerLogout: 'NOT_REQUESTED', mode: 'SYNTHETIC_ONLY',
      });
      await test.step('provider-session-preserved', async () => {
        expect(providerLogoutRequested).toBe(false);
        expect(idpCookiesBefore.length > 0).toBe(true);
        const idpCookiesAfter = (await alpha.cookies(ISSUER + '/protocol/openid-connect/auth'))
          .filter(cookie => cookie.name.startsWith('KEYCLOAK_'))
          .map(({ name, value }) => [name, value]).sort();
        expect(JSON.stringify(idpCookiesBefore) === JSON.stringify(idpCookiesAfter)).toBe(true);
      });
      await expect(alphaPage.locator('#start-login')).toBeVisible();
      expect((await readMe(alphaPage)).status).toBe(401);
      expect((await alpha.cookies(BFF)).some(cookie => cookie.name === SESSION_NAME)).toBe(false);
      // Restoring the retired browser cookie must not revive the server session.
      await alpha.addCookies([{ ...retiredCookie, expires: -1 }]);
      expect((await readMe(alphaPage)).status).toBe(401);
      await alpha.clearCookies({ name: SESSION_NAME });
      await assertOwnAccount(betaPage, credentials.beta.username);
      await test.step('provider-session-preserved', async () => {
        // Real Keycloak SSO succeeds after local logout without entering credentials.
        const authorization = alphaPage.waitForRequest(request =>
          request.url().startsWith(ISSUER + '/protocol/openid-connect/auth'));
        await alphaPage.locator('#start-login').click();
        await authorization;
        await alphaPage.waitForURL(url => url.origin === BFF && url.pathname === '/');
        await expect(alphaPage.locator('#account-id')).toHaveText(credentials.alpha.username);
        await assertOwnAccount(alphaPage, credentials.alpha.username);
      });
      const peerPage = await alphaPeer.newPage();
      await login(peerPage, credentials.alpha);
      await assertOwnAccount(peerPage, credentials.alpha.username);
      await alphaPage.locator('#logout-all').click();
      await expect(alphaPage.locator('#start-login')).toBeVisible();
      expect((await readMe(alphaPage)).status).toBe(401);
      expect((await readMe(peerPage)).status).toBe(401);
      await assertOwnAccount(betaPage, credentials.beta.username);
    });
  } finally {
    await Promise.all([alpha.close(), alphaPeer.close(), beta.close()]);
  }
});

test('[RIO-E2E-05] Expired sessions no longer authorize account access', async ({ browser }) => {
  test.setTimeout(150_000);
  const context = await contextFor(browser);
  try {
    const page = await context.newPage();
    await login(page, credentials.alpha);
    await assertOwnAccount(page, credentials.alpha.username);
    const session = await assertCookie(context, page);
    await test.step('expired-session', async () => {
      // Keep the cookie client-side so this proves server expiry, not only Max-Age.
      await context.addCookies([{ ...session, expires: -1 }]);
      expect((await readMe(page)).status).toBe(200);
      await expect.poll(async () => (await readMe(page)).status, {
        intervals: [1000],
        timeout: 125_000,
      }).toBe(401);
      await page.reload();
      await expect(page.locator('#start-login')).toBeVisible();
      await expect(page.locator('#account-id')).toBeHidden();
      await expect(page.locator('#account-id')).toHaveText('');
    });
  } finally {
    await context.close();
  }
});
