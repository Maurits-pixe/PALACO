import { test, expect } from '@playwright/test';
import {
  BFF, users, login, chooseConsent, nativeConsent, consent, receiptFrom, me,
} from './helpers.mjs';
import {
  postConsentOwnAccountRead, safePostConsentObservation,
} from '../post-consent-observation.mjs';

// Deliberately abort ONLY the page's fetch after a real consent grant.
// Then read the SAME pre-existing synthetic session through Playwright's
// browser-context request channel. Never use that channel to recover a failed
// UI account authorization or to reissue the original page fetch.
//
// If context access succeeds, page-transport failure != proven session expiry.
// It does not establish the cause of any naturally occurring Android failure.
test('[RIO-MOBILE-10] Failed page fetch does not silently revoke or reauthorize session',
  async ({page},testInfo) => {
    const credentials=await users();
    await login(page,credentials.alpha,testInfo);
    const initial=receiptFrom(await consent(page));
    await chooseConsent(page,testInfo);
    const accepted=receiptFrom(await nativeConsent(page,'#consent-save',testInfo));
    expect(accepted.granted).toBe(true);
    expect(accepted.revision).toBe(initial.revision+1);
    const stored=receiptFrom(await consent(page));
    expect(stored.granted).toBe(true);
    expect(stored.revision).toBe(accepted.revision);

    const revisions={grantRevision:accepted.revision,storedRevision:stored.revision};
    let pageReads=0;
    const failOnlyPageRead=async route=>{
      if(route.request().method()==='GET') {
        pageReads++;
        await route.abort('connectionreset');
      } else {
        await route.continue();
      }
    };
    await page.route('**/api/me',failOnlyPageRead);
    const failureInfo={annotations:[]};
    try {
      await test.step('post-consent-page-channel-failure',async()=>{
        let denied=false;
        try {
          await postConsentOwnAccountRead(page,failureInfo,revisions,me);
        } catch {
          denied=true;
        }
        expect(denied).toBe(true);
        expect(pageReads).toBe(1); // No silent retry.
        expect(failureInfo.annotations).toHaveLength(1);
        const observed=safePostConsentObservation(failureInfo.annotations);
        expect(observed?.stage).toBe('after-grant');
        expect(observed?.grantRevision).toBe(accepted.revision);
        expect(observed?.storedRevision).toBe(stored.revision);
        expect(observed?.accountStatus).toBe(null);
        expect(observed?.accountRequestFailed).toBe(true);
        expect(observed?.sessionCookiePresent).toBe(true);
        expect(Object.keys(observed||{}).sort()).toEqual([
          'accountRequestFailed','accountStatus','errorKind',
          'grantRevision','sessionCookiePresent','stage','storedRevision',
        ]);
      });
    } finally {
      await page.unroute('**/api/me',failOnlyPageRead);
    }

    await test.step('post-consent-context-channel-unchanged',async()=>{
      // An explicitly separate diagnostic, never an automatic UI retry.
      const response=await page.context().request.get(BFF+'/api/me',{
        timeout:8000,maxRedirects:0,failOnStatusCode:false,
      });
      try {
        expect(response.status()).toBe(200);
        const data=await response.json();
        expect(data.accountId).toBe('TST-alpha');
        expect(data.mode).toBe('SYNTHETIC_ONLY');
        expect(data.account1).toBe('HOLD');
        expect(data.accountActive).toBe(false);
        expect(data.canOpenContact).toBe(false);
        expect(data.operativeAuthority).toBe('NONE');
      } finally {
        await response.dispose();
      }
      expect(pageReads).toBe(1);
      // Browser page still exists: diagnostic context transport MUST NOT
      // be treated as restored UI/account authorization.
      await expect(page.locator('#account-id')).toHaveText('TST-alpha');
    });

    await test.step('post-consent-revocation-denies-both-channels',async()=>{
      // Saving the stale bearer is strictly in-memory for a synthetic negative
      // test. Never report, print, persist or attach the cookie itself.
      const context=page.context();
      const saved=(await context.cookies(BFF)).find(cookie=>cookie.name==='__Host-rio_session');
      expect(Boolean(saved)).toBe(true);
      const [logoutResponse]=await Promise.all([
        page.waitForResponse(response=>response.url()===BFF+'/auth/logout-all' &&
          response.request().method()==='POST',{timeout:10000}),
        page.locator('#logout-all').click({timeout:10000}),
      ]);
      expect(logoutResponse.status()).toBe(200);
      await expect(page.locator('#feedback')).toHaveText(
        'Lokale testsessie afgemeld. De identity-provider heeft een afzonderlijke sessie.'
      );
      await expect(page.locator('#start-login')).toBeVisible();
      expect((await context.cookies(BFF)).some(cookie=>
        cookie.name==='__Host-rio_session')).toBe(false);
      // Cookie deletion alone is not a server-side revocation test.
      await context.addCookies([{...saved,expires:-1}]);
      expect((await context.cookies(BFF)).some(cookie=>
        cookie.name==='__Host-rio_session')).toBe(true);
      const pageRead=await me(page);
      expect(pageRead.status).toBe(401);
      expect(pageRead.data).toBe(null);
      const contextRead=await context.request.get(BFF+'/api/me',{
        timeout:8000,maxRedirects:0,failOnStatusCode:false,
      });
      try {
        expect(contextRead.status()).toBe(401);
      } finally {
        await contextRead.dispose();
      }
      expect(pageReads).toBe(1); // The synthetic fault still fired once.
      await expect(page.locator('#start-login')).toBeVisible();
      await expect(page.locator('#account-id')).toBeEmpty();
      // Explicitly clear the replayed stale bearer before test cleanup.
      await context.clearCookies({name:'__Host-rio_session'});
    });
  });
