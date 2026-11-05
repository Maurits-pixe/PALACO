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
} finally {
  await browser?.close();
  await server.close();
}
