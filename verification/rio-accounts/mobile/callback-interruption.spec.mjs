import { test, expect } from '@playwright/test';
import {
  BFF, users, contextFor, login, me, consent, receiptFrom, noPersistentState,
} from './helpers.mjs';
import { safeMobileLoginObservation } from '../login-observation.mjs';

// Reproduces a *controlled* navigation-transport failure at the OIDC callback.
// It does not reproduce or explain the historical spontaneous ERR_NETWORK_CHANGED.
test('[RIO-MOBILE-07] Interrupted provider callback cannot grant a session or recover silently',
  async ({ browser }, testInfo) => {
    const credentials = await users();
    const context = await contextFor(browser, testInfo);
    try {
      const page = await context.newPage();
      let intercepted = 0;
      let authStarts = 0;
      const startListener = request => {
        try {
          const url = new URL(request.url());
          if (url.origin === BFF && url.pathname === '/auth/start') authStarts += 1;
        } catch {}
      };
      const abortCallback = async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (request.method() === 'GET' && request.isNavigationRequest()
          && url.origin === BFF && url.pathname === '/auth/callback') {
          intercepted += 1;
          // Deliberate synthetic fault, before BFF can exchange the OIDC code.
          // This keeps all provider secrets and the callback query out of logs.
          await route.abort('connectionreset');
        } else {
          await route.continue();
        }
      };
      page.on('request', startListener);
      await page.route('**/auth/callback**', abortCallback);
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
          expect(intercepted).toBe(1);
          expect(authStarts).toBe(1);
          const observations = testInfo.annotations.filter(
            item => item.type === 'rio-mobile-login-observation');
          expect(observations).toHaveLength(1);
          const observed = safeMobileLoginObservation(observations);
          expect(observed?.actorCase).toBe('alpha');
          expect(observed?.stage).toBe('waiting-for-bff');
          expect(observed?.errorKind).toBe('connection-reset');
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
        await page.unroute('**/auth/callback**', abortCallback);
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
