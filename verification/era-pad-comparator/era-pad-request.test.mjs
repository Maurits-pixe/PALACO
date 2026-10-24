import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compareEraPad, MAX_INPUT_BYTES } from './era-pad-comparator.mjs';
import { compareEraPadJson, compareEraPadJsonForRequest } from './era-pad-json.mjs';

const corpus = JSON.parse(readFileSync(new URL('./era-pad-vectors.v0.1.json', import.meta.url), 'utf8'));
const base = corpus.vectors[0];
const fixture = () => structuredClone(base.input);
const context = () => ({
  assessment_id: base.input.assessment_id,
  request_digest: base.input.request_digest,
});
const encode = input => Buffer.from(JSON.stringify(input));
const invalid = {
  classification: 'SYNTHETIC_ONLY', source_authenticity: 'UNVERIFIED',
  disposition: 'HOLD', operativeAuthority: 'NONE', canOpenContact: false,
  runtimeConnected: false, externalSideEffect: false, commit_order: 'UNKNOWN',
  result: 'REJECTED', reason: 'INVALID_INPUT', binding_status: 'UNKNOWN',
  temporal_status: 'UNKNOWN', pad_status: 'UNKNOWN', integrity_status: 'UNKNOWN',
  normalization_status: 'UNKNOWN',
};
const mismatch = status => ({
  ...status, result: 'REJECTED', reason: 'BINDING_MISMATCH', binding_status: 'MISMATCH',
});
function assertMismatch(report, status = base.expected_status) {
  assert.deepEqual(report, mismatch(status));
  assert.equal(Object.hasOwn(report, 'pad'), false);
  assert.equal(Object.hasOwn(report, 'temporal'), false);
}

test('same bytes match correct context and reject either incorrect expected field without payload', () => {
  const bytes = encode(fixture());
  assert.equal(compareEraPadJsonForRequest(bytes, context()).result, 'CONSISTENT_SYNTHETIC_ONLY');
  for (const [field, value] of [['assessment_id', 'other-request'], ['request_digest', '0'.repeat(64)]]) {
    const expected = { ...context(), [field]: value };
    assertMismatch(compareEraPadJsonForRequest(bytes, expected));
  }
});

test('coherent all-component substitutions and root-only substitutions cannot bypass expected context', () => {
  for (const fields of [
    { assessment_id: 'other-request' }, { request_digest: '0'.repeat(64) },
    { assessment_id: 'other-request', request_digest: '0'.repeat(64) },
  ]) {
    for (const coherent of [true, false]) {
      const input = fixture();
      Object.assign(input, fields);
      if (coherent) for (const part of ['pad', 'temporal']) Object.assign(input[part], fields);
      assertMismatch(compareEraPadJsonForRequest(encode(input), context()));
      if (coherent) {
        assert.equal(compareEraPadJson(encode(input)).binding_status, 'MATCH');
        assert.equal(compareEraPadJsonForRequest(encode(input), { ...context(), ...fields }).result,
          'CONSISTENT_SYNTHETIC_ONLY');
      }
    }
  }
});

test('nested-only substitutions keep the existing inner-binding diagnostic payload', () => {
  for (const parts of [['pad'], ['temporal'], ['pad', 'temporal']]) {
    for (const fields of [
      { assessment_id: 'other-request' }, { request_digest: '0'.repeat(64) },
      { assessment_id: 'other-request', request_digest: '0'.repeat(64) },
    ]) {
      const input = fixture();
      for (const part of parts) Object.assign(input[part], fields);
      const report = compareEraPadJsonForRequest(encode(input), context());
      const { pad, temporal, ...status } = report;
      assert.deepEqual(status, mismatch(base.expected_status));
      assert.deepEqual(pad, input.pad);
      assert.deepEqual(temporal, input.temporal);
      assert.deepEqual(report, compareEraPad(input));
      assert.deepEqual(report, compareEraPadJson(encode(input)));
    }
  }
});

for (const vector of corpus.vectors) {
  test(`matching context preserves both existing APIs and golden statuses: ${vector.id}`, () => {
    const expected = {
      assessment_id: vector.input.assessment_id, request_digest: vector.input.request_digest,
    };
    const bytes = encode(vector.input);
    const report = compareEraPadJsonForRequest(bytes, expected);
    const { pad, temporal, ...status } = report;
    assert.deepEqual(status, vector.expected_status);
    assert.deepEqual(report, compareEraPad(vector.input));
    assert.deepEqual(report, compareEraPadJson(bytes));
    if (vector.structurally_valid) {
      assert.deepEqual(pad, vector.input.pad);
      assert.deepEqual(temporal, vector.input.temporal);
      assertMismatch(compareEraPadJsonForRequest(bytes, { ...expected, assessment_id: 'other-request' }),
        vector.expected_status);
    } else {
      assert.deepEqual(compareEraPadJsonForRequest(bytes, { ...expected, assessment_id: 'other-request' }), invalid);
    }
  });
}

test('invalid contexts reject exact shape, descriptors, types, IDs and digests', () => {
  const bytes = encode(fixture());
  const cases = [
    undefined, null, true, 1, 'context', [], () => {}, new Date(),
    {}, { assessment_id: context().assessment_id }, { request_digest: context().request_digest },
    { ...context(), extra: true }, { ...context(), [Symbol('extra')]: true },
    Object.create(context()), Object.assign(Object.create({ extra: true }), context()),
  ];
  for (const field of ['assessment_id', 'request_digest']) {
    for (const value of [undefined, null, 1, false, {}, [], new String(context()[field])]) {
      cases.push({ ...context(), [field]: value });
    }
    cases.push(Object.defineProperty(context(), field, { enumerable: false }));
  }
  for (const assessment_id of ['', 'x'.repeat(129), 'has space', 'a/b', 'é', 'a\n', '\0']) {
    cases.push({ ...context(), assessment_id });
  }
  for (const request_digest of ['', 'A'.repeat(64), 'g'.repeat(64), 'a'.repeat(63),
    'a'.repeat(65), `${'a'.repeat(63)}\n`, `${'a'.repeat(64)}\n`]) {
    cases.push({ ...context(), request_digest });
  }
  cases.push(Object.defineProperty(context(), 'hidden', { value: true }));
  for (const expected of cases) assert.deepEqual(compareEraPadJsonForRequest(bytes, expected), invalid);
});

test('accessor contexts are rejected without invoking getters or setters', () => {
  let calls = 0;
  for (const field of ['assessment_id', 'request_digest']) {
    for (const descriptor of [
      { get() { calls++; throw new Error('private getter'); } },
      { set(_) { calls++; } },
      { get() { calls++; return context()[field]; }, set(_) { calls++; } },
    ]) {
      const expected = Object.defineProperty(context(), field, { ...descriptor, enumerable: true });
      assert.deepEqual(compareEraPadJsonForRequest(encode(fixture()), expected), invalid);
    }
  }
  assert.equal(calls, 0);
});

test('null prototype and frozen contexts, strict ID boundaries, and caller inputs remain unchanged', () => {
  for (const assessment_id of ['x', 'a'.repeat(128), 'AZaz09._:-']) {
    const input = fixture();
    for (const part of [input, input.pad, input.temporal]) part.assessment_id = assessment_id;
    const expected = { ...context(), assessment_id };
    for (const candidate of [
      expected, Object.freeze({ ...expected }),
      Object.assign(Object.create(null), expected),
      Object.freeze(Object.assign(Object.create(null), expected)),
    ]) {
      const before = Object.getOwnPropertyDescriptors(candidate);
      const bytes = encode(input);
      const originalBytes = Buffer.from(bytes);
      const report = compareEraPadJsonForRequest(bytes, candidate);
      assert.equal(report.result, 'CONSISTENT_SYNTHETIC_ONLY');
      assert.deepEqual(Object.getOwnPropertyDescriptors(candidate), before);
      assert.deepEqual(bytes, originalBytes);
      report.pad.assessment_id = 'changed-output';
      assert.equal(candidate.assessment_id, assessment_id);
      assert.equal(input.pad.assessment_id, assessment_id);
    }
  }
});

test('malformed, oversized, non-byte and schema-invalid input is sanitized before binding mismatch', () => {
  const expected = { ...context(), assessment_id: 'other-request' };
  const json = JSON.stringify(fixture());
  const malformed = [
    undefined, null, {}, json, new Uint16Array(2),
    Buffer.from(''), Buffer.from('{'), Buffer.from('[]'), Buffer.from('{}{}'),
    Buffer.from([0xff]), Buffer.from(`\ufeff${json}`),
    Buffer.from(json.replace('"assessment_id":', '"assessment_id":"duplicate","assessment_id":')),
    Buffer.from(json.replace('"pad":', '"pad":null,"\\u0070ad":')),
    Buffer.from(json.replace('"raw_result":', '"raw_result":"\\ud800","raw_result":')),
    Buffer.alloc(MAX_INPUT_BYTES + 1, ' '),
    encode({ ...fixture(), extra: true }), encode({ ...fixture(), assessment_id: null }),
  ];
  const badNested = fixture();
  badNested.temporal.uncertainty = { value: -1, unit: 'ms' };
  malformed.push(encode(badNested));
  for (const bytes of malformed) assert.deepEqual(compareEraPadJsonForRequest(bytes, expected), invalid);
  assert.deepEqual(invalid, compareEraPad(null));
});

test('shared byte parser honors exact byte budget and Uint8Array subviews', () => {
  const bytes = encode(fixture());
  const padded = Buffer.concat([bytes, Buffer.alloc(MAX_INPUT_BYTES - bytes.length, ' ')]);
  const backing = Buffer.concat([Buffer.from('bad'), padded, Buffer.from('bad')]);
  const view = new Uint8Array(backing.buffer, backing.byteOffset + 3, padded.length);
  assert.deepEqual(compareEraPadJsonForRequest(view, context()), compareEraPad(base.input));
  const spoofed = new Uint8Array(MAX_INPUT_BYTES + 1);
  Object.defineProperty(spoofed, 'byteLength', { value: 0 });
  assert.deepEqual(compareEraPadJsonForRequest(spoofed, context()), invalid);
});

test('descriptor inspection errors are caught without echoing errors', () => {
  const expected = new Proxy(context(), {
    getPrototypeOf() { throw new Error('private context error'); },
  });
  assert.deepEqual(compareEraPadJsonForRequest(encode(fixture()), expected), invalid);
});
