import { test, expect } from '@playwright/test';
import {
  BFF, users, login, activate, chooseConsent, nativeConsent, consent, receiptFrom,
  me, noOverflow, noPersistentState, observeWrites, downloadDraft, isAndroid,
} from './helpers.mjs';
import { postConsentOwnAccountRead } from '../post-consent-observation.mjs';

const IMPORT_ERROR = 'Dit is geen geldig lokaal conceptbestand. Er is niets gewijzigd.';
const EMPTY_AUTHORITY = {
  accountActive: false, canOpenContact: false, operativeAuthority: 'NONE', consentGranted: false,
};

test('[RIO-MOBILE-01] Native consent controls preserve focus and reflow', async ({ page }, testInfo) => {
  const credentials = await users();
  await login(page, credentials.alpha, testInfo);
  const before = receiptFrom(await consent(page));
  await test.step('mobile-login-route', async () => {
    const route = page.locator('#login-route');
    await expect(page.locator('#login-route-title')).toHaveText('Zo werkt de proef');
    await expect(route.locator('li')).toHaveCount(3);
    await expect(page.locator('#login-stage-detail')).toHaveText(
      'Je eigen testsessie is zichtbaar. Bekijk nu jouw keuze voor deze oefensessie.'
    );
    await expect(page.locator('#start-login')).toHaveAttribute('aria-describedby', 'login-stage-detail');
    const writes = observeWrites(page);
    try {
      for (const [index, target] of [[0, '#account-area'], [1, '#account-area'], [2, '#consent-area']]) {
        const link = route.locator('a').nth(index);
        await expect(link).toHaveAttribute('href', target);
        const box = await link.boundingBox();
        expect(Boolean(box && box.width >= 44 && box.height >= 44)).toBe(true);
        await activate(page, link, testInfo);
        expect(new URL(page.url()).hash).toBe(target);
      }
      expect(writes.record.count).toBe(0);
      await noOverflow(page);
      const stillOwn = await me(page);
      expect(stillOwn.status).toBe(200);
      expect(stillOwn.data.accountId).toBe('TST-alpha');
      expect(stillOwn.data.accountActive || stillOwn.data.canOpenContact).toBe(false);
    } finally { writes.stop(); }
  });
  await test.step('mobile-native-semantics', async () => {
    await expect(page.locator('#feedback')).toHaveAttribute('role', 'status');
    await expect(page.locator('#feedback')).toHaveAttribute('aria-live', 'polite');
    await expect(page.locator('#consent-choice')).toMatchAriaSnapshot(
      '- checkbox "Ik geef toestemming voor deze oefensessie. Ik weet dat dit geen persoonlijke toegang geeft."'
    );
    await expect(page.getByLabel('Titel van je concept', { exact: true })).toHaveAttribute('id', 'studio-title');
    await expect(page.getByLabel('Notitie', { exact: true })).toHaveAttribute('id', 'studio-note');
    await expect(page.getByRole('button', { name: 'Mijn keuze bevestigen', exact: true })).toBeDisabled();
    await chooseConsent(page, testInfo);
    if (!isAndroid(testInfo)) {
      await page.keyboard.press('Tab');
      await expect(page.locator('#consent-save')).toBeFocused();
    }
    const accepted = receiptFrom(await nativeConsent(page, '#consent-save', testInfo));
    expect(accepted.granted).toBe(true);
    expect(accepted.revision).toBe(before.revision + 1);
    await expect(page.locator('#feedback')).toHaveText(
      'Je toestemming voor deze oefensessie is bevestigd. Persoonlijke toegang blijft gesloten.'
    );
    await expect(page.locator('#feedback')).toBeFocused();
    const stored = receiptFrom(await consent(page));
    expect(stored.revision).toBe(accepted.revision);
    expect(stored.granted).toBe(true);
    const account = await postConsentOwnAccountRead(page,testInfo,{
      grantRevision:accepted.revision,storedRevision:stored.revision,
    },me);
    expect(account.status).toBe(200); // Existing strict invariant, never retried.
    expect(account.data.accountId).toBe('TST-alpha');
    expect(account.data.accountActive || account.data.canOpenContact).toBe(false);
    const revoked = receiptFrom(await nativeConsent(page, '#consent-revoke', testInfo));
    expect(revoked.granted).toBe(false);
    expect(revoked.revision).toBe(accepted.revision + 1);
    await expect(page.locator('#consent-status')).toHaveText(
      'Je hebt geen actieve toestemming voor deze oefensessie.'
    );
  });
  await test.step('mobile-reflow', async () => {
    await noOverflow(page);
    await page.setViewportSize({ width: 320, height: 800 });
    await noOverflow(page);
    await expect(page.locator('#studio-export')).toBeEnabled();
  });
  await noPersistentState(page);
});

test('[RIO-MOBILE-02] Real local draft downloads cannot become account authority', async ({ page }, testInfo) => {
  const credentials = await users();
  let receiptBefore;
  let privateCsrf;
  let privateCookie;
  const observation = {
    stage: 'login', grantStatus: null, receiptStatus: null, meStatus: null,
    hasSessionCookie: null, accountVisible: false, pageErrors: 0, feedbackBucket: 'unavailable',
  };
  const pageError = () => { observation.pageErrors += 1; };
  page.on('pageerror', pageError);
  try {
    await test.step('mobile-studio-setup', async () => {
      await login(page, credentials.alpha, testInfo);
      observation.stage = 'choose';
      await chooseConsent(page, testInfo);
      observation.stage = 'grant';
      const grant = await nativeConsent(page, '#consent-save', testInfo);
      observation.grantStatus = grant.status;
      receiptFrom(grant);
      observation.stage = 'receipt-read';
      const stored = await consent(page);
      observation.receiptStatus = stored.status;
      receiptBefore = receiptFrom(stored);
      expect(receiptBefore.granted).toBe(true);
      observation.stage = 'me-read';
      const own = await me(page);
      observation.meStatus = own.status;
      expect(own.status).toBe(200);
      expect(typeof own.data?.csrfToken === 'string').toBe(true);
      privateCsrf = own.data.csrfToken;
      observation.stage = 'cookie-read';
      const session = (await page.context().cookies(BFF)).find(cookie => cookie.name === '__Host-rio_session');
      observation.hasSessionCookie = Boolean(session);
      expect(observation.hasSessionCookie).toBe(true);
      privateCookie = session.value;
      observation.stage = 'ready';
    });
  } finally {
    page.off('pageerror', pageError);
    observation.accountVisible = await page.locator('#account-id').isVisible().catch(() => false);
    const feedback = await page.locator('#feedback').textContent({ timeout: 1000 }).catch(() => null);
    observation.feedbackBucket = feedback === null ? 'unavailable' :
      feedback === '' ? 'empty' :
      feedback === 'Je toestemming voor deze oefensessie is bevestigd. Persoonlijke toegang blijft gesloten.' ? 'confirmed' :
      feedback === 'RIO is tijdelijk niet beschikbaar. Controleer je testsessie opnieuw.' ? 'service_unavailable' :
      feedback === 'De testsessie is verlopen of niet meer beschikbaar. Meld je opnieuw aan.' ? 'expired' :
      feedback === 'De testsessie is gewijzigd. Controleer je eigen account opnieuw.' ? 'changed' :
      feedback === 'De testsessie kon niet veilig worden gecontroleerd. Probeer opnieuw.' ? 'invalid_response' : 'other';
    testInfo.annotations.push({ type: 'rio-mobile-studio-setup', description: JSON.stringify(observation) });
  }
  const note = '<img src=x onerror="window.rioDraftInjected=true">\nEen lokaal testconcept.';
  const observer = observeWrites(page);
  try {
    await test.step('mobile-local-download', async () => {
      await page.locator('#studio-title').fill('Mijn lokaal testconcept');
      await page.locator('#studio-note').fill(note);
      const exported = await downloadDraft(page, testInfo);
      expect(exported.value).toEqual({
        schema: 'RIO_LOCAL_DRAFT_V1', verification: 'UNVERIFIED',
        authority: EMPTY_AUTHORITY, draft: { title: 'Mijn lokaal testconcept', note },
      });
      expect([privateCsrf, privateCookie, credentials.alpha.password, credentials.beta.password]
        .every(secret => !exported.text.includes(secret))).toBe(true);
      expect(/access_token|id_token|refresh_token|client_secret|csrfToken|accountId/.test(exported.text)).toBe(false);
      await activate(page, page.locator('#studio-clear'), testInfo);
      await expect(page.locator('#studio-title')).toHaveValue('');
      await expect(page.locator('#studio-note')).toHaveValue('');
      await expect(page.locator('#studio-title')).toBeFocused();
      await page.locator('#studio-import').setInputFiles({
        name: 'rio-lokaal-concept.json', mimeType: 'application/json', buffer: exported.bytes,
      });
      await expect(page.locator('#studio-title')).toHaveValue('Mijn lokaal testconcept');
      await expect(page.locator('#studio-note')).toHaveValue(note);
      await expect(page.locator('#studio-feedback')).toHaveText(
        'Concept geopend, alleen in deze pagina. Het is niet geverifieerd. Je account en toestemming zijn niet gewijzigd.'
      );
      await expect(page.locator('#studio-feedback')).toMatchAriaSnapshot(
        '- status: Concept geopend, alleen in deze pagina. Het is niet geverifieerd. Je account en toestemming zijn niet gewijzigd.'
      );
      const noInjection = await page.evaluate(() =>
        window.rioDraftInjected === undefined && document.querySelector('img[onerror]') === null);
      expect(noInjection).toBe(true);
    });
    await test.step('mobile-import-rejection', async () => {
      const canonical = {
        schema: 'RIO_LOCAL_DRAFT_V1', verification: 'UNVERIFIED',
        authority: EMPTY_AUTHORITY, draft: { title: 'Verboden wijziging', note: 'Testinvoer' },
      };
      const invalid = [
        JSON.stringify({ ...canonical, role: 'OWNER' }),
        JSON.stringify({ ...canonical, access_token: 'SYNTHETIC_REJECTED_INPUT' }),
        JSON.stringify({ ...canonical, draft: { ...canonical.draft, password: 'SYNTHETIC_REJECTED_INPUT' } }),
        JSON.stringify({ ...canonical, authority: { ...EMPTY_AUTHORITY, consentGranted: true } }),
        // Valid JSON and valid field lengths: only the byte-size limit rejects this padded file.
        JSON.stringify(canonical) + ' '.repeat(12288),
      ];
      for (let i = 0; i < invalid.length; i += 1) {
        await activate(page, page.locator('#studio-clear'), testInfo);
        const title = 'Behoud dit lokale concept ' + i;
        await page.locator('#studio-title').fill(title);
        await page.locator('#studio-note').fill('Behoud deze notitie.');
        await page.locator('#studio-import').setInputFiles({
          name: 'onbevestigd-concept.json', mimeType: 'application/json', buffer: Buffer.from(invalid[i], 'utf8'),
        });
        await expect(page.locator('#studio-feedback')).toHaveText(IMPORT_ERROR);
        await expect(page.locator('#studio-title')).toHaveValue(title);
        await expect(page.locator('#studio-note')).toHaveValue('Behoud deze notitie.');
      }
      const last = await downloadDraft(page, testInfo);
      expect(last.value.authority).toEqual(EMPTY_AUTHORITY);
      expect(last.value.verification).toBe('UNVERIFIED');
    });
    await test.step('mobile-studio-isolation', async () => {
      const after = receiptFrom(await consent(page));
      expect(after).toEqual(receiptBefore);
      expect(observer.record.count).toBe(0);
      await noPersistentState(page);
      await page.setViewportSize({ width: 320, height: 800 });
      await noOverflow(page);
    });
  } finally {
    observer.stop();
  }
  // Explicitly close the stored test grant after the local-only privacy observation.
  receiptFrom(await nativeConsent(page, '#consent-revoke', testInfo));
});
