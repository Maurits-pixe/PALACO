import { test, expect } from '@playwright/test';
import {
  BFF, users, login, chooseConsent, consent, nativeConsent, receiptFrom, me,
} from './helpers.mjs';
import {
  postConsentOwnAccountRead, safePostConsentObservation,
} from '../post-consent-observation.mjs';

// These are deliberately local, browser-intercepted negative responses.
// They do not alter PostgreSQL/Keycloak, revoke an actual account, or prove a
// causal explanation for any historical intermittent Android failure.
async function prepareCommittedSyntheticConsent(page, testInfo) {
  const credentials=await users();
  await login(page,credentials.alpha,testInfo);
  const previous=receiptFrom(await consent(page));
  await chooseConsent(page,testInfo);
  const grant=receiptFrom(await nativeConsent(page,'#consent-save',testInfo));
  expect(grant.granted).toBe(true);
  expect(grant.revision).toBe(previous.revision+1);
  const stored=receiptFrom(await consent(page));
  expect(stored.granted).toBe(true);
  expect(stored.revision).toBe(grant.revision);
  return {grantRevision:grant.revision,storedRevision:stored.revision};
}
function safeRecord(info) {
  const observation=safePostConsentObservation(info.annotations);
  expect(info.annotations).toHaveLength(1);
  expect(observation?.stage).toBe('after-grant');
  expect(observation?.grantRevision).toBe(observation?.storedRevision);
  expect(observation?.sessionCookiePresent).toBe(true);
  // No bearer, raw request URL, account identity or other private fields
  // may be materialized in diagnostic evidence.
  expect(Object.keys(observation||{}).sort()).toEqual([
    'accountRequestFailed','accountStatus','errorKind','grantRevision',
    'sessionCookiePresent','stage','storedRevision',
  ]);
  return observation;
}

test('[RIO-MOBILE-08] A forced post-consent 401 is reported without a retry or account grant',
  async ({ page },testInfo) => {
    const revisions=await prepareCommittedSyntheticConsent(page,testInfo);
    let intercepted=0;
    const inject=async route=>{
      if(route.request().method()==='GET') {
        intercepted+=1;
        if(intercepted===1) {
          await route.fulfill({
            status:401,contentType:'application/json',body:'{"error":"unauthorized"}',
            headers:{'cache-control':'no-store'},
          });
          return;
        }
      }
      await route.continue();
    };
    await page.route('**/api/me',inject);
    const info={annotations:[]};
    try {
      await test.step('post-consent-http-denial',async()=>{
        const response=await postConsentOwnAccountRead(page,info,revisions,me);
        // This must remain the non-200 response, not a silently retried success.
        expect(response.status).toBe(401);
        expect(response.data).toBe(null);
        expect(intercepted).toBe(1);
        const observed=safeRecord(info);
        expect(observed?.accountStatus).toBe(401);
        expect(observed?.accountRequestFailed).toBe(false);
        expect(observed?.errorKind).toBe('other');
        expect(observed?.grantRevision).toBe(revisions.grantRevision);
        expect(observed?.storedRevision).toBe(revisions.storedRevision);
      });
    } finally {
      await page.unroute('**/api/me',inject);
    }
  });

test('[RIO-MOBILE-09] A forced post-consent transport reset preserves the original failure',
  async ({ page },testInfo) => {
    const revisions=await prepareCommittedSyntheticConsent(page,testInfo);
    let intercepted=0;
    const inject=async route=>{
      if(route.request().method()==='GET') {
        intercepted+=1;
        if(intercepted===1) {
          await route.abort('connectionreset');
          return;
        }
      }
      await route.continue();
    };
    await page.route('**/api/me',inject);
    const info={annotations:[]};
    try {
      await test.step('post-consent-transport-denial',async()=>{
        let rejected=false;
        try {
          await postConsentOwnAccountRead(page,info,revisions,me);
        } catch {
          // No exception text is saved to CI evidence.
          rejected=true;
        }
        expect(rejected).toBe(true);
        expect(intercepted).toBe(1); // Never silently reissue the account GET.
        const observed=safeRecord(info);
        expect(observed?.accountStatus).toBe(null);
        expect(observed?.accountRequestFailed).toBe(true);
        expect(['other','connection-reset','network-changed','aborted']).toContain(observed?.errorKind);
        expect(observed?.grantRevision).toBe(revisions.grantRevision);
        expect(observed?.storedRevision).toBe(revisions.storedRevision);
      });
    } finally {
      await page.unroute('**/api/me',inject);
    }
  });
