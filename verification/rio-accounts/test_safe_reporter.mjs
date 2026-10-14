import assert from 'node:assert/strict';
import test from 'node:test';
import { safeDurableLoginObservation } from './safe-reporter.mjs';

const allowed = {
  actorCase: 'alphaPeer', stage: 'waiting-for-account', pageKind: 'bff-home',
  loginButtonVisible: false, accountVisible: true,
  meStatuses: [401, 200], consentStatuses: [503],
  meRequestFailed: false, consentRequestFailed: true, feedbackBucket: 'service_unavailable',
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
    { endpoint: '/api/me?token=PRIVATE' }, { statuses: { '/api/consent': [200] } },
    { path: '/auth/callback?code=PRIVATE' },
  ]) assert.equal(safeDurableLoginObservation(annotate({ ...allowed, ...extra })), undefined);
});

test('rejects forged case, stage, page and visibility values', () => {
  for (const change of [
    { actorCase: 'real-person' }, { stage: 'callback?state=PRIVATE' },
    { pageKind: 'https://example.invalid/?token=PRIVATE' },
    { loginButtonVisible: 'true' }, { accountVisible: 1 },
    { meRequestFailed: 'false' }, { consentRequestFailed: null },
    { feedbackBucket: 'PRIVATE' },
  ]) assert.equal(safeDurableLoginObservation(annotate({ ...allowed, ...change })), undefined);
});

test('safely preserves explicit missing observations', () => {
  const value = { ...allowed, pageKind: 'unavailable', loginButtonVisible: null, accountVisible: null };
  assert.deepEqual(safeDurableLoginObservation(annotate(value)), value);
  for (const feedbackBucket of [
    'unavailable', 'empty', 'confirmed', 'service_unavailable', 'expired', 'changed', 'invalid_response', 'other',
  ]) {
    const bucket = { ...allowed, feedbackBucket };
    assert.deepEqual(safeDurableLoginObservation(annotate(bucket)), bucket);
  }
});

test('rejects oversized payloads without echoing their content', () => {
  assert.equal(safeDurableLoginObservation(annotate('PRIVATE'.repeat(100))), undefined);
  assert.equal(safeDurableLoginObservation(annotate(allowed, 'untrusted')) , undefined);
});

test('rejects forged, unbounded or secret-bearing endpoint statuses without leaking paths', () => {
  for (const change of [
    { meStatuses: [99] }, { consentStatuses: [600] }, { meStatuses: [200.5] },
    { meStatuses: ['200'] }, { consentStatuses: [null] }, { meStatuses: Array(9).fill(200) },
    { consentStatuses: { '/api/consent?token=PRIVATE': 200 } },
    { meStatuses: ['https://localhost:8088/api/me?token=PRIVATE'] },
    { consentStatuses: [{ status: 503, path: '/api/consent?token=PRIVATE' }] },
  ]) {
    const observation = safeDurableLoginObservation(annotate({ ...allowed, ...change }));
    assert.equal(observation, undefined);
    assert.equal(JSON.stringify({ observation }).includes('PRIVATE'), false);
  }
  const bounded = { ...allowed, meStatuses: Array(8).fill(100), consentStatuses: Array(8).fill(599) };
  assert.deepEqual(safeDurableLoginObservation(annotate(bounded)), bounded);
});
