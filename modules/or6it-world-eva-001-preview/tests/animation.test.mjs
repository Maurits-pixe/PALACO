import test from 'node:test';
import assert from 'node:assert/strict';
import { startAmbientAnimation } from '../src/animation.js';

function createHarness() {
  const callbacks = new Map();
  const windowListeners = new Map();
  const documentListeners = new Map();
  const mediaListeners = new Map();
  const calls = { arcs: 0, clears: 0, particles: [] };
  let nextFrame = 0;
  const mediaQuery = {
    matches: false,
    addEventListener: (type, listener) => mediaListeners.set(type, listener),
    removeEventListener: type => mediaListeners.delete(type),
  };
  const context = {
    setTransform() {},
    clearRect() { calls.clears += 1; },
    beginPath() {},
    arc(x, y, radius) {
      calls.arcs += 1;
      calls.particles.push([x, y, radius]);
    },
    fill() {},
  };
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => context,
    getBoundingClientRect: () => ({ width: 720, height: 400 }),
  };
  const windowObject = {
    devicePixelRatio: 2,
    matchMedia: () => mediaQuery,
    requestAnimationFrame: callback => {
      const id = ++nextFrame;
      callbacks.set(id, callback);
      return id;
    },
    cancelAnimationFrame: id => callbacks.delete(id),
    addEventListener: (type, listener) => windowListeners.set(type, listener),
    removeEventListener: type => windowListeners.delete(type),
  };
  const documentObject = {
    hidden: false,
    addEventListener: (type, listener) => documentListeners.set(type, listener),
    removeEventListener: type => documentListeners.delete(type),
  };
  function runFrame(timestamp) {
    const [id, callback] = callbacks.entries().next().value;
    callbacks.delete(id);
    callback(timestamp);
  }
  return {
    callbacks, canvas, calls, documentListeners, documentObject,
    mediaListeners, mediaQuery, runFrame, windowListeners, windowObject,
  };
}

test('ambient motion pauses while hidden and resumes without replacing its loop', () => {
  const harness = createHarness();
  const animation = startAmbientAnimation(harness.canvas, harness);
  assert.equal(harness.callbacks.size, 1);
  harness.runFrame(17);
  assert.ok(harness.calls.arcs > 0);
  const pausedParticles = harness.calls.particles.slice(-40);

  harness.documentObject.hidden = true;
  harness.documentListeners.get('visibilitychange')();
  assert.equal(harness.callbacks.size, 0);

  harness.documentObject.hidden = false;
  harness.documentListeners.get('visibilitychange')();
  assert.equal(harness.callbacks.size, 1);
  harness.runFrame(1000);
  assert.ok(harness.calls.arcs > 1);
  assert.deepEqual(harness.calls.particles.slice(-40), pausedParticles);

  animation.dispose();
  assert.equal(harness.callbacks.size, 0);
  assert.equal(harness.documentListeners.size, 0);
  assert.equal(harness.mediaListeners.size, 0);
  assert.equal(harness.windowListeners.size, 0);
});

test('repeated visibility changes keep one frame loop and disposal while hidden stays stopped', () => {
  const harness = createHarness();
  const animation = startAmbientAnimation(harness.canvas, harness);

  harness.documentObject.hidden = true;
  harness.documentListeners.get('visibilitychange')();
  harness.documentListeners.get('visibilitychange')();
  assert.equal(harness.callbacks.size, 0);

  harness.documentObject.hidden = false;
  harness.documentListeners.get('visibilitychange')();
  harness.documentListeners.get('visibilitychange')();
  assert.equal(harness.callbacks.size, 1);
  harness.runFrame(17);
  assert.equal(harness.callbacks.size, 1);

  harness.documentObject.hidden = true;
  harness.documentListeners.get('visibilitychange')();
  animation.dispose();
  harness.documentObject.hidden = false;
  animation.setEnabled(true);
  animation.setEnabled(false);
  assert.equal(harness.documentListeners.size, 0);
  assert.equal(harness.callbacks.size, 0);
});

test('resize updates canvas backing scale without starting a second frame loop', () => {
  const harness = createHarness();
  const context = harness.canvas.getContext();
  const transforms = [];
  harness.canvas.getBoundingClientRect = () => ({ width: 360, height: 240 });
  harness.windowObject.devicePixelRatio = 3;
  harness.canvas.getContext = () => ({
    ...context,
    setTransform: (...values) => transforms.push(values),
  });
  const animation = startAmbientAnimation(harness.canvas, harness);

  assert.equal(harness.canvas.width, 720);
  assert.equal(harness.canvas.height, 480);
  assert.deepEqual(transforms, [[2, 0, 0, 2, 0, 0]]);
  assert.equal(harness.callbacks.size, 1);

  harness.canvas.getBoundingClientRect = () => ({ width: 180, height: 120 });
  harness.windowListeners.get('resize')();
  assert.equal(harness.canvas.width, 360);
  assert.equal(harness.canvas.height, 240);
  assert.deepEqual(transforms.at(-1), [2, 0, 0, 2, 0, 0]);
  assert.equal(harness.callbacks.size, 1);

  harness.documentObject.hidden = true;
  harness.documentListeners.get('visibilitychange')();
  harness.canvas.getBoundingClientRect = () => ({ width: 540, height: 300 });
  harness.windowListeners.get('resize')();
  assert.equal(harness.canvas.width, 1080);
  assert.equal(harness.canvas.height, 600);
  assert.equal(harness.callbacks.size, 0);

  harness.documentObject.hidden = false;
  harness.documentListeners.get('visibilitychange')();
  assert.equal(harness.callbacks.size, 1);

  harness.mediaQuery.matches = true;
  harness.mediaListeners.get('change')();
  harness.canvas.getBoundingClientRect = () => ({ width: 270, height: 150 });
  harness.windowListeners.get('resize')();
  assert.equal(harness.canvas.width, 540);
  assert.equal(harness.canvas.height, 300);
  assert.equal(harness.callbacks.size, 0);

  harness.mediaQuery.matches = false;
  harness.mediaListeners.get('change')();
  assert.equal(harness.callbacks.size, 1);
  animation.dispose();
});

test('zero-sized canvas does not schedule animation frames until it becomes visible', () => {
  const harness = createHarness();
  harness.canvas.getBoundingClientRect = () => ({ width: 0, height: 0 });
  const animation = startAmbientAnimation(harness.canvas, harness);

  assert.equal(harness.canvas.width, 0);
  assert.equal(harness.canvas.height, 0);
  assert.equal(harness.callbacks.size, 0);

  harness.canvas.getBoundingClientRect = () => ({ width: 360, height: 200 });
  harness.windowListeners.get('resize')();
  assert.equal(harness.canvas.width, 720);
  assert.equal(harness.canvas.height, 400);
  assert.equal(harness.callbacks.size, 1);

  animation.dispose();
});

test('reduced motion disables the canvas loop and can be changed at runtime', () => {
  const harness = createHarness();
  const animation = startAmbientAnimation(harness.canvas, harness);
  harness.mediaQuery.matches = true;
  harness.mediaListeners.get('change')();
  assert.equal(harness.callbacks.size, 0);

  harness.mediaQuery.matches = false;
  harness.mediaListeners.get('change')();
  assert.equal(harness.callbacks.size, 1);
  animation.dispose();
});

test('manual pause stops rendering and resume respects system reduced motion', () => {
  const harness = createHarness();
  const animation = startAmbientAnimation(harness.canvas, harness);
  assert.equal(harness.callbacks.size, 1);

  animation.setEnabled(false);
  assert.equal(harness.callbacks.size, 0);
  animation.setEnabled(true);
  assert.equal(harness.callbacks.size, 1);

  harness.mediaQuery.matches = true;
  harness.mediaListeners.get('change')();
  assert.equal(harness.callbacks.size, 0);
  animation.setEnabled(false);
  animation.setEnabled(true);
  assert.equal(harness.callbacks.size, 0);

  harness.mediaQuery.matches = false;
  harness.mediaListeners.get('change')();
  assert.equal(harness.callbacks.size, 1);
  animation.dispose();
});

test('pause and resume preserve animation time rather than skipping ahead', () => {
  const harness = createHarness();
  const animation = startAmbientAnimation(harness.canvas, harness);

  harness.runFrame(17);
  const pausedParticles = harness.calls.particles.slice(-40);
  animation.setEnabled(false);
  animation.setEnabled(true);
  harness.runFrame(20_000);

  assert.deepEqual(harness.calls.particles.slice(-40), pausedParticles);
  animation.dispose();
});

test('missing canvas context keeps the animation controller contract', () => {
  const harness = createHarness();
  harness.canvas.getContext = () => null;
  const animation = startAmbientAnimation(harness.canvas, harness);

  assert.equal(typeof animation.setEnabled, 'function');
  assert.equal(typeof animation.dispose, 'function');
  assert.doesNotThrow(() => animation.setEnabled(false));
  assert.doesNotThrow(() => animation.dispose());
  assert.equal(harness.callbacks.size, 0);
  assert.equal(harness.windowListeners.size, 0);
});
