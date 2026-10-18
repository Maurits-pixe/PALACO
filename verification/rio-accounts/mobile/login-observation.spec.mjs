import { test, expect } from '@playwright/test';
import {
  BFF, users, contextFor, login, me, consent, receiptFrom, noPersistentState,
} from './helpers.mjs';
import { safeMobileLoginObservation } from '../login-observation.mjs';

test('[RIO-MOBILE-06] Failed initial navigation stays closed until an explicit fresh login', async ({ browser }, testInfo) => {
  const credentials = await users();
  const context = await contextFor(browser, testInfo);
  try {
    const page = await context.newPage();
    const counts = { initialNavigations: 0, bffAuth: 0, bffApi: 0, provider: 0 };
    const requestListener = request => {
      const url = new URL(request.url());
      if (url.origin === BFF) {
        if (url.pathname.startsWith('/auth/')) counts.bffAuth += 1;
        if (url.pathname.startsWith('/api/')) counts.bffApi += 1;
      }
      if (url.origin === 'http://127.0.0.1:8089') counts.provider += 1;
    };
    page.on('request', requestListener);
    const initialUrl = url => url.href === BFF + '/';
    const abortInitialNavigation = async route => {
      const request = route.request();
      if (request.method() === 'GET' && request.isNavigationRequest() &&
          request.frame() === page.mainFrame()) {
        counts.initialNavigations += 1;
        await route.abort('connectionrefused');
      } else {
        await route.continue();
      }
    };
    await page.route(initialUrl, abortInitialNavigation);
    try {
      await test.step('mobile-navigation-failure', async () => {
        let rejected = false;
        try {
          await login(page, credentials.alpha, testInfo);
        } catch {
          // The helper captures only allowlisted diagnostics. Never retain the raw error.
          rejected = true;
        }
        expect(rejected).toBe(true);
        expect(counts).toEqual({ initialNavigations: 1, bffAuth: 0, bffApi: 0, provider: 0 });
        expect((await context.cookies()).length).toBe(0);
        const captured = testInfo.annotations.filter(item => item.type === 'rio-mobile-login-observation');
        expect(captured.length).toBe(1);
        const observed = safeMobileLoginObservation(captured);
        expect(observed?.accountVisible === null || observed?.accountVisible === false).toBe(true);
        expect(observed?.loginButtonVisible === null || observed?.loginButtonVisible === false).toBe(true);
        expect(observed).toEqual({
          actorCase: 'alpha', stage: 'opening-bff', pageKind: 'other',
          accountVisible: observed.accountVisible, loginButtonVisible: observed.loginButtonVisible,
          documentStatuses: [], meStatuses: [], consentStatuses: [],
          documentRequestFailed: true, meRequestFailed: false, consentRequestFailed: false,
          errorKind: 'connection-refused', feedbackBucket: 'unavailable',
        });
        // This expected observation has been checked. A later unexpected failure
        // must report its own observation rather than this deliberately injected one.
        const index = testInfo.annotations.indexOf(captured[0]);
        testInfo.annotations.splice(index, 1);
      });
    } finally {
      await page.unroute(initialUrl, abortInitialNavigation);
      page.off('request', requestListener);
    }

    await test.step('mobile-explicit-login-recovery', async () => {
      // Removing the injection does not authorize anything: this is a separate,
      // explicit login through the unchanged real local OIDC and PKCE contract.
      await login(page, credentials.alpha, testInfo);
      const account = await me(page);
      expect(account.status).toBe(200);
      expect(account.data.accountId).toBe('TST-alpha');
      expect(account.data.accountActive).toBe(false);
      expect(account.data.canOpenContact).toBe(false);
      receiptFrom(await consent(page));
      expect((await context.cookies(BFF)).some(cookie =>
        cookie.name === '__Host-rio_session' && cookie.secure && cookie.httpOnly &&
        cookie.domain === 'localhost' && cookie.path === '/' && cookie.sameSite === 'Lax')).toBe(true);
      await noPersistentState(page);
      expect(testInfo.annotations.some(item => item.type === 'rio-mobile-login-observation')).toBe(false);
    });
  } finally {
    await context.close();
  }
});
