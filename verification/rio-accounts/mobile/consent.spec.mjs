import { test, expect } from '@playwright/test';
import {
  BFF, SCOPE, users, contextFor, login, activate, chooseConsent, nativeConsent,
  me, consent, writeConsent, receiptFrom, retainCookie, noPersistentState,
  downloadDraft, controlFixture, observeWrites,
} from './helpers.mjs';

test('[RIO-MOBILE-03] Own consent uses session CSRF and a fresh choice after CAS conflict', async ({ browser }, testInfo) => {
  const credentials = await users();
  const contexts = await Promise.all([contextFor(browser, testInfo), contextFor(browser, testInfo), contextFor(browser, testInfo)]);
  try {
    const pages = await Promise.all(contexts.map(context => context.newPage()));
    await login(pages[0], credentials.alpha, testInfo);
    await login(pages[1], credentials.alpha, testInfo);
    await login(pages[2], credentials.beta, testInfo);
    const accounts = await Promise.all(pages.map(page => me(page)));
    expect(accounts.every(result => result.status === 200)).toBe(true);
    const csrf = accounts.map(result => result.data.csrfToken);
    expect(new Set(csrf).size).toBe(3);
    let alphaReceipt = receiptFrom(await consent(pages[0]));
    let betaReceipt = receiptFrom(await consent(pages[2]));
    alphaReceipt = receiptFrom(await writeConsent(pages[0], { scope: SCOPE, granted: false, revision: alphaReceipt.revision }, csrf[0]));
    betaReceipt = receiptFrom(await writeConsent(pages[2], { scope: SCOPE, granted: false, revision: betaReceipt.revision }, csrf[2]));
    await test.step('mobile-consent-isolation', async () => {
      const body = { scope: SCOPE, granted: true, revision: alphaReceipt.revision };
      expect((await writeConsent(pages[0], body, csrf[2])).status).toBe(403);
      expect((await writeConsent(pages[0], body, csrf[1])).status).toBe(403);
      expect((await writeConsent(pages[2], { ...body, revision: betaReceipt.revision }, csrf[0])).status).toBe(403);
      expect((await writeConsent(pages[0], { ...body, accountId: 'TST-beta' }, csrf[0])).status).toBe(400);
      expect(receiptFrom(await consent(pages[0]))).toEqual(alphaReceipt);
      expect(receiptFrom(await consent(pages[2]))).toEqual(betaReceipt);
    });
    for (const page of pages.slice(0, 2)) {
      const [response] = await Promise.all([
        page.waitForResponse(response => response.url() === BFF + '/api/consent' && response.request().method() === 'GET'),
        activate(page, page.locator('#consent-refresh'), testInfo),
      ]);
      expect(response.status()).toBe(200);
      await expect(page.locator('#consent-choice')).toBeEnabled();
      await chooseConsent(page, testInfo);
    }
    const observers = pages.slice(0, 2).map(page => observeWrites(page));
    try {
      await test.step('mobile-consent-cas', async () => {
        const outcomes = await Promise.all(pages.slice(0, 2).map(page => nativeConsent(page, '#consent-save', testInfo)));
        expect(outcomes.map(result => result.status).sort()).toEqual([200, 409]);
        const winner = outcomes.findIndex(result => result.status === 200);
        const loser = 1 - winner;
        const accepted = receiptFrom(outcomes[winner]);
        expect(accepted.revision).toBe(alphaReceipt.revision + 1);
        await expect(pages[loser].locator('#feedback')).toHaveText(
          'De keuze is intussen gewijzigd. Bekijk de huidige keuze en kies opnieuw.'
        );
        await expect(pages[loser].locator('#consent-choice')).not.toBeChecked();
        await expect(pages[loser].locator('#consent-save')).toBeDisabled();
        expect(observers.reduce((sum, item) => sum + item.record.count, 0)).toBe(2);
        await chooseConsent(pages[loser], testInfo);
        const fresh = receiptFrom(await nativeConsent(pages[loser], '#consent-save', testInfo));
        expect(fresh.revision).toBe(accepted.revision + 1);
        expect(fresh.granted).toBe(true);
        expect(receiptFrom(await consent(pages[2]))).toEqual(betaReceipt);
        const revoked = receiptFrom(await nativeConsent(pages[loser], '#consent-revoke', testInfo));
        expect(revoked.granted).toBe(false);
        expect(receiptFrom(await consent(pages[winner]))).toEqual(revoked);
      });
    } finally {
      observers.forEach(observer => observer.stop());
    }
  } finally {
    await Promise.all(contexts.map(context => context.close()));
  }
});

test('[RIO-MOBILE-04] Real expiry closes consent while preserving the local draft', async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const credentials = await users();
  await login(page, credentials.alpha, testInfo);
  const account = (await me(page)).data;
  await chooseConsent(page, testInfo);
  const grant = receiptFrom(await nativeConsent(page, '#consent-save', testInfo));
  await retainCookie(page.context());
  await page.locator('#studio-title').fill('Lokaal concept bij sessieverval');
  await page.locator('#studio-note').fill('Deze lokale notitie blijft beschikbaar.');
  await page.locator('#consent-refresh').focus();
  await test.step('mobile-expiry-closure', async () => {
    // The UI verifies /api/me every10s: keep the cookie so this proves server absolute expiry.
    await expect.poll(async () => (await consent(page)).status, { intervals: [1000], timeout: 75_000 }).toBe(401);
    await expect(page.locator('#start-login')).toBeVisible();
    await expect(page.locator('#account-id')).toBeHidden();
    await expect(page.locator('#account-id')).toHaveText('');
    await expect(page.locator('#consent-panel')).toBeHidden();
    for (const id of ['consent-choice', 'consent-save', 'consent-revoke', 'consent-refresh']) {
      await expect(page.locator('#' + id)).toBeDisabled();
    }
    await expect(page.locator('#feedback')).toBeFocused();
    expect((await writeConsent(page, { scope: SCOPE, granted: true, revision: grant.revision }, account.csrfToken)).status).toBe(401);
    await expect(page.locator('#studio-title')).toHaveValue('Lokaal concept bij sessieverval');
    const downloaded = await downloadDraft(page, testInfo);
    expect(downloaded.value.authority.consentGranted).toBe(false);
    expect(downloaded.value.verification).toBe('UNVERIFIED');
    await noPersistentState(page);
  });
});

test('[RIO-MOBILE-05] Database uncertainty closes the UI until explicit recovery', async ({ page }, testInfo) => {
  const credentials = await users();
  let databaseMayBeStopped = false;
  let bffNeedsRecovery = false;
  try {
    await login(page, credentials.alpha, testInfo);
    const account = (await me(page)).data;
    const currentReceipt = receiptFrom(await consent(page));
    const originalReceipt = receiptFrom(await writeConsent(page, {
      scope: SCOPE, granted: false, revision: currentReceipt.revision,
    }, account.csrfToken));
    const cookie = await retainCookie(page.context());
    await page.locator('#studio-note').fill('Lokaal blijven werken bij een storing.');
    await page.locator('#consent-refresh').focus();
    await test.step('mobile-database-closure', async () => {
      databaseMayBeStopped = true;
      bffNeedsRecovery = true;
      await controlFixture('stop-db');
      expect((await consent(page)).status).toBe(503);
      expect((await writeConsent(page, { scope: SCOPE, granted: true, revision: originalReceipt.revision }, account.csrfToken)).status).toBe(503);
      // A real failed consent refresh or the10s own-session check clears privileged UI.
      if (await page.locator('#consent-refresh').isVisible() && await page.locator('#consent-refresh').isEnabled()) {
        await activate(page, page.locator('#consent-refresh'), testInfo);
      }
      await expect(page.locator('#retry-session')).toBeVisible({ timeout: 12_000 });
      await expect(page.locator('#account-id')).toHaveText('');
      await expect(page.locator('#consent-panel')).toBeHidden();
      await expect(page.locator('#consent-save')).toBeDisabled();
      await expect(page.locator('#feedback')).toBeFocused();
      await expect(page.locator('#studio-note')).toHaveValue('Lokaal blijven werken bij een storing.');
    });
    await test.step('mobile-explicit-recovery', async () => {
      await controlFixture('start-db');
      databaseMayBeStopped = false;
      expect((await consent(page)).status).toBe(503);
      await controlFixture('restart-bff');
      bffNeedsRecovery = false;
      // Readiness cannot silently reopen the old view: a native explicit retry is required.
      await expect(page.locator('#account-id')).toHaveText('');
      await expect(page.locator('#retry-session')).toBeVisible();
      await activate(page, page.locator('#retry-session'), testInfo);
      await expect(page.locator('#account-id')).toHaveText('TST-alpha');
      await expect(page.locator('#consent-refresh')).toBeEnabled();
      const restored = (await me(page)).data;
      expect(restored.csrfToken === account.csrfToken).toBe(true);
      expect((await page.context().cookies(BFF)).some(value =>
        value.name === '__Host-rio_session' && value.value === cookie.value)).toBe(true);
      expect(receiptFrom(await consent(page))).toEqual(originalReceipt);
      await noPersistentState(page);
    });
  } finally {
    if (databaseMayBeStopped) await controlFixture('start-db');
    if (bffNeedsRecovery) await controlFixture('restart-bff');
  }
});
