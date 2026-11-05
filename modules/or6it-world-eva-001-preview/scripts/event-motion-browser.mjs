import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { preview } from 'vite';

const server = await preview({
  configFile: fileURLToPath(new URL('../vite.config.js', import.meta.url)),
  preview: { host: '127.0.0.1', port: 0, strictPort: false },
});
let browser;

try {
  const address = server.httpServer.address();
  assert.ok(address && typeof address === 'object');
  browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {}),
  });
  const page = await browser.newPage({ reducedMotion: 'no-preference' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.addInitScript(() => {
    const nativeRequest = window.requestAnimationFrame.bind(window);
    const callbacks = new Set();
    window.__evaMotionProbe = { callbacks, frames: 0 };
    window.requestAnimationFrame = callback => {
      callbacks.add(callback);
      return nativeRequest(timestamp => {
        window.__evaMotionProbe.frames++;
        callback(timestamp);
      });
    };
  });
  await page.goto(`http://127.0.0.1:${address.port}`);
  await page.waitForFunction(() => window.__evaMotionProbe.frames >= 5, null, { polling: 20 });
  assert.equal((await page.locator('.sequence-badge').textContent()).trim(), 'SEQUENCE 41');
  await page.evaluate(() => {
    const ring = document.querySelector('.ring-system');
    const animation = ring.getAnimations()[0];
    window.__evaMotionBefore = {
      ring,
      animation,
      time: animation.currentTime,
      startTime: animation.startTime,
      frames: window.__evaMotionProbe.frames,
      callbacks: [...window.__evaMotionProbe.callbacks],
    };
  });

  await page.getByRole('button', { name: 'Toon volgend fixture-event' }).click();
  await page.waitForFunction(() =>
    document.querySelector('.sequence-badge').textContent.trim() === 'SEQUENCE 42' &&
    document.querySelector('.scene').classList.contains('event-pulse'), null, { polling: 20 });
  await page.waitForFunction(
    () => !document.querySelector('.scene').classList.contains('event-pulse'),
    null,
    { polling: 20 },
  );
  const result = await page.evaluate(() => {
    const before = window.__evaMotionBefore;
    const ring = document.querySelector('.ring-system');
    const animation = ring.getAnimations()[0];
    return {
      sameRing: ring === before.ring,
      sameAnimation: animation === before.animation,
      sameStartTime: animation.startTime === before.startTime,
      progressed: animation.currentTime > before.time,
      running: animation.playState === 'running',
      canvasAdvanced: window.__evaMotionProbe.frames > before.frames,
      sameCanvasCallbacks: window.__evaMotionProbe.callbacks.size === before.callbacks.length &&
        before.callbacks.every(callback => window.__evaMotionProbe.callbacks.has(callback)),
    };
  });
  for (const [check, passed] of Object.entries(result)) assert.equal(passed, true, check);
  assert.equal(await page.locator('.event-list li').count(), 2);
  assert.equal(await page.getByRole('button', { name: 'Fixture-event getoond' }).isDisabled(), true);
  assert.deepEqual(errors, []);
  console.log('Event/motion browser regression passed:', result);

  await page.reload();
  await page.waitForFunction(() => window.__evaMotionProbe.frames >= 5, null, { polling: 20 });
  await page.getByRole('button', { name: 'Pauzeer beweging' }).click();
  const resumeButton = page.getByRole('button', { name: 'Hervat beweging' });
  await resumeButton.waitFor();
  assert.equal(await resumeButton.getAttribute('aria-pressed'), 'false');
  await page.evaluate(async () => {
    const animations = ['.ring-system', '.core-mark'].map(selector =>
      document.querySelector(selector).getAnimations()[0]);
    await Promise.all(animations.map(animation => animation.ready));
    window.__evaPaused = {
      animations,
      times: animations.map(animation => animation.currentTime),
      frames: window.__evaMotionProbe.frames,
      callbacks: [...window.__evaMotionProbe.callbacks],
    };
  });
  await page.getByRole('button', { name: 'Toon volgend fixture-event' }).click();
  await page.waitForFunction(
    () => document.querySelector('.sequence-badge').textContent.trim() === 'SEQUENCE 42' &&
      !document.querySelector('.scene').classList.contains('event-pulse'),
    null,
    { polling: 20 },
  );
  const pausedResult = await page.evaluate(() => {
    const before = window.__evaPaused;
    return {
      svgStillPaused: before.animations.every(animation => animation.playState === 'paused'),
      svgPhaseUnchanged: before.animations.every((animation, index) =>
        animation.currentTime === before.times[index]),
      canvasStillPaused: window.__evaMotionProbe.frames === before.frames,
    };
  });
  for (const [check, passed] of Object.entries(pausedResult)) assert.equal(passed, true, check);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('button', { name: 'Beweging beperkt door systeem' }).waitFor();
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await resumeButton.waitFor();
  assert.equal(await resumeButton.getAttribute('aria-pressed'), 'false');
  assert.equal(await page.evaluate(() =>
    window.__evaMotionProbe.frames === window.__evaPaused.frames), true);

  await resumeButton.click();
  await page.waitForFunction(() => {
    const before = window.__evaPaused;
    return before.animations.every((animation, index) =>
      animation.playState === 'running' && animation.currentTime > before.times[index]) &&
      window.__evaMotionProbe.frames > before.frames;
  }, null, { polling: 20 });
  assert.equal(await page.evaluate(() =>
    ['.ring-system', '.core-mark'].every((selector, index) =>
      document.querySelector(selector).getAnimations()[0] === window.__evaPaused.animations[index]) &&
    window.__evaMotionProbe.callbacks.size === window.__evaPaused.callbacks.length &&
    window.__evaPaused.callbacks.every(callback => window.__evaMotionProbe.callbacks.has(callback))),
  true);
  assert.equal(await page.getByRole('button', { name: 'Pauzeer beweging' }).getAttribute('aria-pressed'), 'true');
  console.log('Manual pause survives fixture events and preference changes; original animations resume.');

  await page.evaluate(() => {
    window.__evaVisibilityBefore = {
      animations: ['.ring-system', '.core-mark'].map(selector =>
        document.querySelector(selector).getAnimations()[0]),
      times: ['.ring-system', '.core-mark'].map(selector =>
        document.querySelector(selector).getAnimations()[0].currentTime),
    };
  });
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForFunction(
    () => document.querySelector('.scene').classList.contains('motion-paused'),
    null,
    { polling: 20 },
  );
  const hiddenFrames = await page.evaluate(() => window.__evaMotionProbe.frames);
  await page.waitForTimeout(150);
  assert.equal(await page.evaluate(() => window.__evaMotionProbe.frames), hiddenFrames);
  assert.equal(await page.evaluate(() =>
    window.__evaVisibilityBefore.animations.every(animation => animation.playState === 'paused')), true);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForFunction(
    () => !document.querySelector('.scene').classList.contains('motion-paused'),
    null,
    { polling: 20 },
  );
  await page.waitForFunction(beforeFrames =>
    window.__evaMotionProbe.frames > beforeFrames &&
    ['.ring-system', '.core-mark'].every(selector =>
      document.querySelector(selector).getAnimations()[0].playState === 'running'),
  hiddenFrames, { polling: 20 });
  assert.equal(await page.evaluate(() =>
    ['.ring-system', '.core-mark'].every((selector, index) =>
      document.querySelector(selector).getAnimations()[0] === window.__evaVisibilityBefore.animations[index] &&
      document.querySelector(selector).getAnimations()[0].currentTime > window.__evaVisibilityBefore.times[index])),
  true);
  console.log('Synthetic visibilitychange pauses Canvas/SVG motion and resumes the same animations.');

  await page.getByRole('button', { name: 'Pauzeer beweging' }).click();
  const manualPauseFrames = await page.evaluate(() => window.__evaMotionProbe.frames);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForFunction(
    () => document.querySelector('.scene').classList.contains('motion-paused'),
    null,
    { polling: 20 },
  );
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForFunction(
    () => document.querySelector('.scene').classList.contains('motion-paused'),
    null,
    { polling: 20 },
  );
  assert.equal(await page.getByRole('button', { name: 'Hervat beweging' }).getAttribute('aria-pressed'), 'false');
  assert.equal(await page.evaluate(() => window.__evaMotionProbe.frames), manualPauseFrames);
  assert.equal(await page.evaluate(() =>
    window.__evaVisibilityBefore.animations.every(animation => animation.playState === 'paused')), true);
  await page.getByRole('button', { name: 'Hervat beweging' }).click();
  await page.waitForFunction(beforeFrames =>
    !document.querySelector('.scene').classList.contains('motion-paused') &&
    window.__evaMotionProbe.frames > beforeFrames,
  manualPauseFrames, { polling: 20 });
  assert.equal(await page.evaluate(() =>
    ['.ring-system', '.core-mark'].every((selector, index) =>
      document.querySelector(selector).getAnimations()[0] === window.__evaVisibilityBefore.animations[index] &&
      document.querySelector(selector).getAnimations()[0].playState === 'running')),
  true);
  console.log('Manual pause remains active across hide/show visibility changes until resumed.');

  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.reload();
    const motionButton = page.getByRole('button', { name: 'Beweging beperkt door systeem' });
    await motionButton.waitFor();
    assert.equal(await motionButton.isDisabled(), true);
    await page.getByRole('button', { name: 'Toon volgend fixture-event' }).click();
    await page.waitForFunction(
      () => document.querySelector('.sequence-badge').textContent.trim() === 'SEQUENCE 42' &&
        !document.querySelector('.scene').classList.contains('event-pulse'),
      null,
      { polling: 20 },
    );
    await page.waitForFunction(() => document.querySelector('.reference-image').naturalWidth > 0, null, { polling: 20 });
    const reduced = await page.evaluate(() => ({
      canvasFrames: window.__evaMotionProbe.frames,
      ringPaused: getComputedStyle(document.querySelector('.ring-system')).animationPlayState === 'paused',
      corePaused: getComputedStyle(document.querySelector('.core-mark')).animationPlayState === 'paused',
      noHorizontalOverflow: document.documentElement.scrollWidth <= innerWidth,
      imageLoaded: document.querySelector('.reference-image').naturalWidth > 0,
    }));
    assert.equal(reduced.canvasFrames, 0, 'Reduced motion must not schedule Canvas frames.');
    for (const check of ['ringPaused', 'corePaused', 'noHorizontalOverflow', 'imageLoaded']) {
      assert.equal(reduced[check], true, `${width}px: ${check}`);
    }
    assert.equal(await page.locator('.event-list li').count(), 2);
    console.log(`Reduced-motion mobile regression passed (${width}px):`, reduced);
  }

  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.waitForFunction(() => window.__evaMotionProbe.frames >= 5, null, { polling: 20 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('button', { name: 'Beweging beperkt door systeem' }).waitFor();
  const stoppedAt = await page.evaluate(() => window.__evaMotionProbe.frames);
  await page.waitForTimeout(150);
  assert.equal(await page.evaluate(() => window.__evaMotionProbe.frames), stoppedAt);
  assert.deepEqual(errors, []);
  console.log('Runtime reduced-motion preference change passed.');

  const cryptoFailurePage = await browser.newPage({ reducedMotion: 'reduce' });
  cryptoFailurePage.on('pageerror', error => errors.push(error.message));
  cryptoFailurePage.on('console', message => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await cryptoFailurePage.addInitScript(() => {
    Object.defineProperty(crypto.subtle, 'digest', {
      value: () => Promise.reject(new Error('Synthetic SHA-256 failure.')),
    });
  });
  await cryptoFailurePage.goto(`http://127.0.0.1:${address.port}`);
  const fingerprintStatus = cryptoFailurePage.locator('.fingerprint-row [role="status"]');
  await fingerprintStatus.getByText('Fingerprint niet beschikbaar: Synthetic SHA-256 failure.', { exact: true }).waitFor();
  assert.match(await fingerprintStatus.textContent(), /UNAVAILABLE/);
  assert.equal(await fingerprintStatus.locator('code').count(), 0);
  await cryptoFailurePage.getByRole('button', { name: 'Toon volgend fixture-event' }).click();
  await cryptoFailurePage.waitForFunction(
    () => document.querySelector('.sequence-badge').textContent.trim() === 'SEQUENCE 42',
    null,
    { polling: 20 },
  );
  assert.deepEqual(errors, []);
  await cryptoFailurePage.close();
  console.log('Fingerprint failure is visible without a fabricated digest; fixture events remain usable.');

  const keyboardPage = await browser.newPage({ reducedMotion: 'no-preference' });
  keyboardPage.on('pageerror', error => errors.push(error.message));
  keyboardPage.on('console', message => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await keyboardPage.goto(`http://127.0.0.1:${address.port}`);
  const skipLink = keyboardPage.getByRole('link', { name: 'Ga naar inhoud' });
  await keyboardPage.keyboard.press('Tab');
  assert.equal(await skipLink.evaluate(element => element === document.activeElement), true);
  assert.ok(await skipLink.evaluate(element => element.getBoundingClientRect().top >= 0));
  await keyboardPage.keyboard.press('Enter');
  await keyboardPage.waitForFunction(() => location.hash === '#main-content');
  assert.equal(await keyboardPage.locator('#main-content').evaluate(element => element === document.activeElement), true);
  await keyboardPage.keyboard.press('Tab');
  const motionButton = keyboardPage.getByRole('button', { name: 'Pauzeer beweging' });
  assert.equal(await motionButton
    .evaluate(element => element === document.activeElement), true);
  await keyboardPage.keyboard.press('Enter');
  const keyboardResumeButton = keyboardPage.getByRole('button', { name: 'Hervat beweging' });
  await keyboardResumeButton.waitFor();
  assert.equal(await keyboardResumeButton.getAttribute('aria-pressed'), 'false');
  await keyboardPage.keyboard.press('Tab');
  const eventButton = keyboardPage.getByRole('button', { name: 'Toon volgend fixture-event' });
  assert.equal(await eventButton.evaluate(element => element === document.activeElement), true);
  await keyboardPage.keyboard.press('Enter');
  await keyboardPage.waitForFunction(
    () => document.querySelector('.sequence-badge').textContent.trim() === 'SEQUENCE 42',
    null,
    { polling: 20 },
  );
  assert.equal(await keyboardPage.getByRole('button', { name: 'Fixture-event getoond' }).isDisabled(), true);
  await keyboardPage.emulateMedia({ reducedMotion: 'reduce' });
  await keyboardPage.getByRole('button', { name: 'Beweging beperkt door systeem' }).waitFor();
  await keyboardPage.keyboard.press('Tab');
  assert.equal(await keyboardPage.locator('.manifest-details summary')
    .evaluate(element => element === document.activeElement), true);
  assert.deepEqual(errors, []);
  await keyboardPage.close();
  console.log('Keyboard skip link, motion state, event activation, and disabled state passed.');
} finally {
  await browser?.close();
  await server.close();
}
