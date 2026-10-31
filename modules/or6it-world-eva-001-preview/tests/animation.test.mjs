import test from 'node:test';
import assert from 'node:assert/strict';
import { startAmbientAnimation } from '../src/animation.js';

function createHarness() {
  const callbacks = new Map();
  const windowListeners = new Map();
  const documentListeners = new Map();
  const mediaListeners = new Map();
  const calls = { arcs: 0, clears: 0 };
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
    arc() { calls.arcs += 1; },
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
  const stop = startAmbientAnimation(harness.canvas, harness);
  assert.equal(harness.callbacks.size, 1);
  harness.runFrame(17);
  assert.ok(harness.calls.arcs > 0);

  harness.documentObject.hidden = true;
  harness.documentListeners.get('visibilitychange')();
  assert.equal(harness.callbacks.size, 0);

  harness.documentObject.hidden = false;
  harness.documentListeners.get('visibilitychange')();
  assert.equal(harness.callbacks.size, 1);
  harness.runFrame(1000);
  assert.ok(harness.calls.arcs > 1);

  stop();
  assert.equal(harness.callbacks.size, 0);
  assert.equal(harness.documentListeners.size, 0);
  assert.equal(harness.mediaListeners.size, 0);
  assert.equal(harness.windowListeners.size, 0);
});

test('reduced motion disables the canvas loop and can be changed at runtime', () => {
  const harness = createHarness();
  const stop = startAmbientAnimation(harness.canvas, harness);
  harness.mediaQuery.matches = true;
  harness.mediaListeners.get('change')();
  assert.equal(harness.callbacks.size, 0);

  harness.mediaQuery.matches = false;
  harness.mediaListeners.get('change')();
  assert.equal(harness.callbacks.size, 1);
  stop();
});
