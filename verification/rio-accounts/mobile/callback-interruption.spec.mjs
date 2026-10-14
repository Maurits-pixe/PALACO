import { test, expect } from '@playwright/test';
import {
  BFF, users, contextFor, login, me, consent, receiptFrom, noPersistentState,
} from './helpers.mjs';
import { safeMobileLoginObservation } from '../login-observation.mjs';

// Reproduces a *controlled* transport failure on the provider credential POST,
// before the browser can follow the OIDC redirect to BFF. Playwright routes
// the original request, not each hop in a redirect chain.
// It does not explain the historical spontaneous ERR_NETWORK_CHANGED.
test('[RIO-MOBILE-07] Interrupted provider submission cannot grant a session or recover silently',
  async ({ browser }, testInfo) => {
    const credentials = await users();
    const context = await contextFor(browser, testInfo);
    try {
      const page = await context.newPage();
      let interruptedSubmissions = 0;
      let callbackRequests = 0;
      let authStarts = 0;
      const startListener = request => {
        try {
          const url = new URL(request.url());
          if (url.origin === BFF && url.pathname === '/auth/start') authStarts += 1;
          if (url.origin === BFF && url.pathname === '/auth/callback') callbackRequests += 1;
        } catch {}
      };
      const abortCallback = async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (request.method() === 'POST' && url.origin === 'http://127.0.0.1:8089' &&
            url.pathname.startsWith('/realms/rio-synthetic/login-actions/authenticate')) {
          interruptedSubmissions += 1;
          // Deliberate synthetic fault on the *original* provider POST, before
          // any OIDC redirect or BFF callback. Never inspect its request body.
          await route.abort('connectionreset');
        } else {
          await route.continue();
        }
      };
      page.on('request', startListener);
      // Intercept only the original Keycloak credential POST. Redirected
      // callbacks are not separately routable by Playwright (docs/network).
      await context.route('**/*', abortCallback);
      try {
        await test.step('mobile-callback-interruption', async () => {
          let failed = false;
          try {
            await login(page, credentials.alpha, testInfo);
          } catch {
            // The helper emits only an allowlisted, secret-free login observation.
            failed = true;
          }
          expect(failed).toBe(true);
          expect(interruptedSubmissions).toBe(1);
          expect(callbackRequests).toBe(0);
          expect(authStarts).toBe(1);
          const observations = testInfo.annotations.filter(
            item => item.type === 'rio-mobile-login-observation');
          expect(observations).toHaveLength(1);
          const observed = safeMobileLoginObservation(observations);
          expect(observed?.actorCase).toBe('alpha');
          expect(observed?.stage).toBe('waiting-for-bff');
          expect(observed?.errorKind).toBe('connection-reset');
          // Prove the private transport breadcrumb identifies exactly the
          // original interrupted provider POST, not a delivered BFF callback.
          expect(observed?.providerSubmitRequests).toBe(1);
          expect(observed?.providerSubmitRequestFailed).toBe(true);
          expect(observed?.callbackRequests).toBe(0);
          expect(observed?.callbackStatuses).toEqual([]);
          expect(observed?.callbackRequestFailed).toBe(false);
          expect(observed?.accountVisible).not.toBe(true);
          // Context-bound read instead of page.evaluate on an error document.
          // A callback not delivered to BFF cannot mint a session.
          const response = await context.request.get(BFF + '/api/me', {
            timeout: 8000, maxRedirects: 0, failOnStatusCode: false,
          });
          try { expect(response.status()).toBe(401); }
          finally { await response.dispose(); }
          expect((await context.cookies(BFF)).some(cookie =>
            cookie.name === '__Host-rio_session')).toBe(false);
          expect(authStarts).toBe(1); // No automatic retry or second grant.
          // The injected observation was examined; the next real login may
          // only leave independent unexpected evidence of its own.
          for (const item of observations) {
            const index = testInfo.annotations.indexOf(item);
            if (index >= 0) testInfo.annotations.splice(index, 1);
          }
        });
      } finally {
        await context.unroute('**/*', abortCallback);
        page.off('request', startListener);
      }
      await test.step('mobile-callback-explicit-recovery', async () => {
        // Deliberately start a *new* OIDC/PKCE exchange, never replay the old
        // interrupted callback or reuse a provider code as account authority.
        await login(page, credentials.alpha, testInfo);
        const current = await me(page);
        expect(current.status).toBe(200);
        expect(current.data.accountId).toBe('TST-alpha');
        expect(current.data.accountActive).toBe(false);
        expect(current.data.canOpenContact).toBe(false);
        receiptFrom(await consent(page));
        await noPersistentState(page);
        expect(testInfo.annotations.some(item =>
          item.type === 'rio-mobile-login-observation')).toBe(false);
      });
    } finally {
      await context.close();
    }
  });
