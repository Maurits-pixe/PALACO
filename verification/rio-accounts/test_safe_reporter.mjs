import assert from 'node:assert/strict';
import test from 'node:test';
import { safeDurableLoginObservation } from './safe-reporter.mjs';

const allowed = {
  actorCase: 'alphaPeer', stage: 'waiting-for-account', pageKind: 'bff-home',
  loginButtonVisible: false, accountVisible: true,
};
const annotate = (value, type = 'rio-durable-login-observation') => [
  { type, description: typeof value === 'string' ? value : JSON.stringify(value) },
];

test('allows only typed synthetic login metadata', () => {
  assert.deepEqual(safeDurableLoginObservation(annotate(allowed)), allowed);
});

test('missing or duplicate annotations produce no observation', () => {
  assert.equal(safeDurableLoginObservation([]), undefined);
  assert.equal(safeDurableLoginObservation([...annotate(allowed), ...annotate(allowed)]), undefined);
  assert.equal(safeDurableLoginObservation(annotate('{')), undefined);
});

test('rejects arbitrary URLs, credentials, error messages and extra keys', () => {
  for (const extra of [
    { url: 'https://example.invalid/secret?code=PRIVATE' },
    { access_token: 'PRIVATE' }, { error: 'PRIVATE' }, { username: 'PRIVATE' },
  ]) assert.equal(safeDurableLoginObservation(annotate({ ...allowed, ...extra })), undefined);
});

test('rejects forged case, stage, page and visibility values', () => {
  for (const change of [
    { actorCase: 'real-person' }, { stage: 'callback?state=PRIVATE' },
    { pageKind: 'https://example.invalid/?token=PRIVATE' },
    { loginButtonVisible: 'true' }, { accountVisible: 1 },
  ]) assert.equal(safeDurableLoginObservation(annotate({ ...allowed, ...change })), undefined);
});

test('safely preserves explicit missing observations', () => {
  const value = { ...allowed, pageKind: 'unavailable', loginButtonVisible: null, accountVisible: null };
  assert.deepEqual(safeDurableLoginObservation(annotate(value)), value);
});

test('rejects oversized payloads without echoing their content', () => {
  assert.equal(safeDurableLoginObservation(annotate('PRIVATE'.repeat(100))), undefined);
  assert.equal(safeDurableLoginObservation(annotate(allowed, 'untrusted')) , undefined);
});
