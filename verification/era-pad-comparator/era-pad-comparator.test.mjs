import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { compareEraPad, SCHEMA_VERSION, MAX_RAW_BYTES, MAX_INPUT_BYTES } from './era-pad-comparator.mjs';

const hash = raw => createHash('sha256').update(raw, 'utf8').digest('hex');
function fixture(raw = 'PASS', normalized = raw) {
  return {
    schema_version: SCHEMA_VERSION, classification: 'SYNTHETIC_ONLY',
    source_authenticity: 'UNVERIFIED', assessment_id: 'fixture-A', request_digest: 'a'.repeat(64),
    pad: {
      assessment_id: 'fixture-A', request_digest: 'a'.repeat(64),
      observation_id: 'observation-1', raw_result: raw, raw_result_sha256: hash(raw),
      normalized_result: normalized,
    },
    temporal: {
      assessment_id: 'fixture-A', request_digest: 'a'.repeat(64),
      source_kind: 'SYNTHETIC_FIXTURE',
      observed_at: '2026-10-20T10:00:00.000Z', recorded_at: '2026-10-20T10:00:00.000Z',
      sync_status: 'SYNCHRONIZED', uncertainty: { value: 0, unit: 'ms' },
    },
  };
}
function closed(output) {
  assert.equal(output.disposition, 'HOLD');
  assert.equal(output.operativeAuthority, 'NONE');
  for (const key of ['canOpenContact', 'runtimeConnected', 'externalSideEffect']) assert.equal(output[key], false);
  assert.equal(output.source_authenticity, 'UNVERIFIED');
  assert.equal(output.commit_order, 'UNKNOWN');
}
function compare(input) {
  const output = compareEraPad(input);
  closed(output);
  return output;
}
function invalid(input) {
  const output = compare(input);
  assert.equal(output.result, 'REJECTED');
  assert.equal(output.reason, 'INVALID_INPUT');
  assert.equal(output.pad, undefined);
}

test('consistent synthetic fixture retains independent statuses and never order or authority', () => {
  const output = compare(fixture());
  assert.equal(output.result, 'CONSISTENT_SYNTHETIC_ONLY');
  assert.equal(output.binding_status, 'MATCH');
  assert.equal(output.integrity_status, 'MATCH');
  assert.equal(output.temporal_status, 'KNOWN');
  assert.equal(output.pad_status, 'PASS');
});

test('cross-assessment and request substitutions rejected in both components', () => {
  for (const component of ['pad', 'temporal']) {
    for (const [field, value] of [['assessment_id', 'fixture-B'], ['request_digest', 'b'.repeat(64)]]) {
      const input = fixture();
      input[component][field] = value;
      const output = compare(input);
      assert.equal(output.reason, 'BINDING_MISMATCH');
      assert.equal(output.result, 'REJECTED');
      assert.equal(output.integrity_status, 'MATCH');
    }
  }
});

test('raw bytes are not trimmed, case-folded or Unicode-normalized', () => {
  for (const raw of [' PASS', 'PASS\n', 'pass', 'e\u0301', '\u00e9', '🙂', '']) {
    const input = fixture(raw, 'UNKNOWN');
    assert.equal(compare(input).result, 'CONSISTENT_SYNTHETIC_ONLY');
    input.pad.raw_result += ' ';
    const output = compare(input);
    assert.equal(output.result, 'INTEGRITY_MISMATCH');
    assert.equal(output.pad.raw_result, `${raw} `);
  }
  assert.notEqual(hash('e\u0301'), hash('\u00e9'));
});

test('errors, timeout, unknown and free text cannot hide behind positive normalization', () => {
  for (const raw of ['ERROR', 'TIMEOUT', 'UNKNOWN', 'FAIL', 'all fine', ' PASS ']) {
    assert.equal(compare(fixture(raw, 'PASS')).reason, 'NORMALIZATION_MISMATCH');
    const code = ['ERROR', 'TIMEOUT', 'UNKNOWN', 'FAIL'].includes(raw) ? raw : 'UNKNOWN';
    assert.equal(compare(fixture(raw, code)).pad_status, code);
  }
});

test('missing or uncertain time retains PAD observations', () => {
  const variants = [
    { observed_at: null }, { recorded_at: null }, { uncertainty: null },
    { uncertainty: { value: 0.1, unit: 's' } },
    { sync_status: 'UNKNOWN' }, { sync_status: 'UNSYNCHRONIZED' }, { source_kind: 'UNKNOWN' },
  ];
  for (const fields of variants) {
    const input = fixture();
    Object.assign(input.temporal, fields);
    const output = compare(input);
    assert.equal(output.result, 'CONSISTENT_SYNTHETIC_ONLY');
    assert.equal(output.temporal_status, 'UNKNOWN');
    assert.deepEqual(output.pad, input.pad);
  }
});

test('strict calendar timestamps and explicit uncertainty units/types', () => {
  for (const timestamp of [
    '2026-02-30T00:00:00.000Z', '2026-10-20', '2026-10-20T10:00:00Z',
    '2026-10-20T10:00:00.000+00:00', '2026-10-20T10:00:60.000Z',
    '0000-01-01T00:00:00.000Z', true, 1,
  ]) {
    const input = fixture();
    input.temporal.observed_at = timestamp;
    invalid(input);
  }
  for (const uncertainty of [
    { value: -1, unit: 'ms' }, { value: -0, unit: 'ms' }, { value: Infinity, unit: 's' },
    { value: NaN, unit: 'ms' }, { value: '0', unit: 'ms' }, { value: 0, unit: 'seconds' },
    { value: 86_400_001, unit: 'ms' }, { value: 86_401, unit: 's' }, {},
  ]) {
    const input = fixture();
    input.temporal.uncertainty = uncertainty;
    invalid(input);
  }
  for (const unit of ['s', 'ms']) {
    const input = fixture();
    input.temporal.uncertainty = { value: unit === 's' ? 86_400 : 86_400_000, unit };
    assert.equal(compare(input).temporal_status, 'UNKNOWN');
  }
});

test('schema/types/extra authority and seal fields are closed', () => {
  for (const fields of [
    { schema_version: 'other' }, { classification: 'REAL' },
    { source_authenticity: 'VERIFIED' }, { operativeAuthority: 'NONE' },
    { seal: null }, { assessment_id: null }, { pad: [] }, { temporal: null },
  ]) invalid(Object.assign(fixture(), fields));
  for (const component of ['pad', 'temporal']) {
    const input = fixture();
    input[component].signature = 'forbidden';
    invalid(input);
  }
  for (const digest of ['A'.repeat(64), 'a'.repeat(63), 123, null, 'z'.repeat(64)]) {
    const input = fixture();
    input.pad.raw_result_sha256 = digest;
    invalid(input);
  }
  for (const value of [null, [], false, '{}', undefined]) invalid(value);
});

test('exact ID, UTF-8 raw and serialized byte limits', () => {
  for (const length of [1, 128]) {
    const input = fixture();
    input.assessment_id = input.pad.assessment_id = input.temporal.assessment_id = 'a'.repeat(length);
    assert.equal(compare(input).result, 'CONSISTENT_SYNTHETIC_ONLY');
  }
  for (const length of [0, 129]) {
    const input = fixture(); input.pad.observation_id = 'a'.repeat(length); invalid(input);
  }
  assert.equal(compare(fixture('🙂'.repeat(MAX_RAW_BYTES / 4), 'UNKNOWN')).result, 'CONSISTENT_SYNTHETIC_ONLY');
  invalid(fixture('🙂'.repeat(MAX_RAW_BYTES / 4) + 'a', 'UNKNOWN'));
  invalid(fixture('\ud800', 'UNKNOWN'));
  // JSON escapes count as six bytes, whereas raw SHA-256 still covers the single NUL byte.
  const base = Buffer.byteLength(JSON.stringify(fixture('', 'UNKNOWN')));
  const room = MAX_INPUT_BYTES - base;
  const raw = '\0'.repeat(Math.floor(room / 6)) + 'a'.repeat(room % 6);
  const exact = fixture(raw, 'UNKNOWN');
  assert.equal(Buffer.byteLength(JSON.stringify(exact)), MAX_INPUT_BYTES);
  assert.equal(compare(exact).result, 'CONSISTENT_SYNTHETIC_ONLY');
  invalid(fixture(raw + 'a', 'UNKNOWN'));
});

test('plain data only: getters, exotic objects, symbols and cycles rejected without access', () => {
  const input = fixture();
  Object.defineProperty(input.pad, 'raw_result', { enumerable: true, get() { throw new Error('must not execute'); } });
  invalid(input);
  const symbol = fixture(); symbol[Symbol('seal')] = true; invalid(symbol);
  const cyclic = fixture(); cyclic.temporal.uncertainty = cyclic; invalid(cyclic);
  const exotic = fixture(); Object.setPrototypeOf(exotic.pad, { authority: true }); invalid(exotic);
});

test('repeat is deterministic, input is unchanged, output owns independent data', () => {
  const input = fixture();
  const before = structuredClone(input);
  const first = compare(input);
  assert.deepEqual(compare(input), first);
  assert.deepEqual(input, before);
  first.pad.raw_result = 'changed';
  first.temporal.uncertainty.value = 100;
  assert.deepEqual(input, before);
  assert.equal(compare(input).pad.raw_result, 'PASS');
});

test('binding, integrity and normalization keep their independent diagnostic evidence', () => {
  const input = fixture('ERROR', 'PASS');
  input.temporal.assessment_id = 'other';
  input.pad.raw_result_sha256 = '0'.repeat(64);
  const output = compare(input);
  assert.equal(output.reason, 'BINDING_MISMATCH');
  assert.equal(output.integrity_status, 'INTEGRITY_MISMATCH');
  assert.equal(output.normalization_status, 'MISMATCH');
  assert.equal(output.pad_status, 'ERROR');
});
