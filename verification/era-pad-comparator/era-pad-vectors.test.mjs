import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { compareEraPad } from './era-pad-comparator.mjs';
import { compareEraPadJson } from './era-pad-json.mjs';

const corpus = JSON.parse(readFileSync(new URL('./era-pad-vectors.v0.1.json', import.meta.url), 'utf8'));
const cli = fileURLToPath(new URL('./era-pad-cli.mjs', import.meta.url));
const statusKeys = [
  'classification', 'source_authenticity', 'disposition', 'operativeAuthority',
  'canOpenContact', 'runtimeConnected', 'externalSideEffect', 'commit_order',
  'result', 'reason', 'binding_status', 'temporal_status', 'pad_status',
  'integrity_status', 'normalization_status',
];
const requiredIds = [
  'synthetic-pass-known-time', 'synthetic-fail-consistent', 'synthetic-error-consistent',
  'synthetic-timeout-consistent', 'synthetic-unknown-consistent', 'synthetic-unicode-free-text',
  'synthetic-unknown-temporal-context', 'synthetic-missing-temporal-context',
  'synthetic-binding-over-integrity-and-normalization', 'synthetic-integrity-over-normalization',
  'synthetic-normalization-mismatch', 'synthetic-extra-authority-sanitized',
];
const keys = (value, expected) => assert.deepEqual(Object.keys(value).sort(), [...expected].sort());

function closed(status) {
  keys(status, statusKeys);
  assert.equal(status.classification, 'SYNTHETIC_ONLY');
  assert.equal(status.source_authenticity, 'UNVERIFIED');
  assert.equal(status.disposition, 'HOLD');
  assert.equal(status.operativeAuthority, 'NONE');
  assert.equal(status.commit_order, 'UNKNOWN');
  for (const key of ['canOpenContact', 'runtimeConnected', 'externalSideEffect']) {
    assert.equal(status[key], false);
  }
}

test('fixed golden corpus has exact versioned schema, named coverage and closed status snapshots', () => {
  keys(corpus, ['corpus_version', 'classification', 'source_authenticity', 'vectors']);
  assert.equal(corpus.corpus_version, 'ERA_PAD_VECTORS_V0.1');
  assert.equal(corpus.classification, 'SYNTHETIC_ONLY');
  assert.equal(corpus.source_authenticity, 'UNVERIFIED');
  assert.ok(Array.isArray(corpus.vectors));
  const ids = corpus.vectors.map(vector => vector.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.deepEqual([...ids].sort(), [...requiredIds].sort());
  for (const vector of corpus.vectors) {
    keys(vector, ['id', 'structurally_valid', 'input', 'expected_status', 'expected_cli_exit']);
    assert.match(vector.id, /^synthetic-[a-z-]+$/);
    assert.equal(typeof vector.structurally_valid, 'boolean');
    assert.equal(vector.input.schema_version, 'ERA_PAD_COMPARATOR_V1');
    assert.equal(vector.input.classification, 'SYNTHETIC_ONLY');
    assert.equal(vector.input.source_authenticity, 'UNVERIFIED');
    assert.match(vector.input.pad.raw_result_sha256, /^[a-f0-9]{64}$/);
    closed(vector.expected_status);
    assert.equal(vector.expected_cli_exit,
      vector.expected_status.result === 'CONSISTENT_SYNTHETIC_ONLY' ? 0 : 2);
  }

  const byId = id => corpus.vectors.find(vector => vector.id === `synthetic-${id}`);
  for (const [code, name] of [
    ['PASS', 'pass-known-time'], ['FAIL', 'fail-consistent'], ['ERROR', 'error-consistent'],
    ['TIMEOUT', 'timeout-consistent'], ['UNKNOWN', 'unknown-consistent'],
  ]) {
    const vector = byId(name);
    assert.equal(vector.input.pad.raw_result, code);
    assert.equal(vector.input.pad.normalized_result, code);
    assert.equal(vector.expected_status.pad_status, code);
    assert.equal(vector.expected_status.result, 'CONSISTENT_SYNTHETIC_ONLY');
    assert.equal(vector.expected_status.reason, null);
    assert.equal(vector.expected_status.temporal_status, 'KNOWN');
    assert.equal(vector.expected_cli_exit, 0);
    assert.equal(vector.structurally_valid, true);
  }
  const unicode = byId('unicode-free-text');
  assert.equal(unicode.input.pad.raw_result, 'Fictional café e\u0301 🙂');
  assert.equal(unicode.input.pad.normalized_result, 'UNKNOWN');
  assert.equal(unicode.expected_status.pad_status, 'UNKNOWN');
  assert.equal(unicode.expected_status.result, 'CONSISTENT_SYNTHETIC_ONLY');
  const unknown = byId('unknown-temporal-context');
  assert.equal(unknown.input.temporal.source_kind, 'UNKNOWN');
  assert.equal(unknown.input.temporal.sync_status, 'UNKNOWN');
  const missing = byId('missing-temporal-context');
  for (const field of ['observed_at', 'recorded_at', 'uncertainty']) {
    assert.equal(missing.input.temporal[field], null);
  }
  for (const vector of [unknown, missing]) {
    assert.equal(vector.structurally_valid, true);
    assert.equal(vector.expected_status.temporal_status, 'UNKNOWN');
    assert.equal(vector.expected_status.result, 'CONSISTENT_SYNTHETIC_ONLY');
    assert.equal(vector.expected_status.pad_status, vector.input.pad.raw_result);
  }
  for (const [name, result, reason, binding, integrity] of [
    ['binding-over-integrity-and-normalization', 'REJECTED', 'BINDING_MISMATCH', 'MISMATCH', 'INTEGRITY_MISMATCH'],
    ['integrity-over-normalization', 'INTEGRITY_MISMATCH', 'INTEGRITY_MISMATCH', 'MATCH', 'INTEGRITY_MISMATCH'],
    ['normalization-mismatch', 'REJECTED', 'NORMALIZATION_MISMATCH', 'MATCH', 'MATCH'],
  ]) {
    const vector = byId(name);
    assert.equal(vector.structurally_valid, true);
    assert.equal(vector.input.pad.raw_result, 'ERROR');
    assert.equal(vector.input.pad.normalized_result, 'PASS');
    assert.equal(vector.expected_status.result, result);
    assert.equal(vector.expected_status.reason, reason);
    assert.equal(vector.expected_status.binding_status, binding);
    assert.equal(vector.expected_status.integrity_status, integrity);
    assert.equal(vector.expected_status.normalization_status, 'MISMATCH');
  }
  const invalid = byId('extra-authority-sanitized');
  assert.equal(invalid.structurally_valid, false);
  assert.equal(invalid.input.operativeAuthority, 'FICTIONAL_OPEN');
  assert.equal(invalid.expected_status.result, 'REJECTED');
  assert.equal(invalid.expected_status.reason, 'INVALID_INPUT');
  for (const field of ['binding_status', 'temporal_status', 'pad_status', 'integrity_status', 'normalization_status']) {
    assert.equal(invalid.expected_status[field], 'UNKNOWN');
  }
});

for (const vector of corpus.vectors) {
  test(`shared golden object/bytes/CLI conformance: ${vector.id}`, { timeout: 5000 }, async t => {
    const before = structuredClone(vector.input);
    const bytes = Buffer.from(JSON.stringify(vector.input), 'utf8');
    for (const report of [compareEraPad(vector.input), compareEraPadJson(bytes)]) {
      const { pad, temporal, ...status } = report;
      closed(status);
      assert.deepEqual(status, vector.expected_status);
      if (vector.structurally_valid) {
        keys(report, [...statusKeys, 'pad', 'temporal']);
        for (const [field, value] of [['pad', pad], ['temporal', temporal]]) {
          assert.deepEqual(value, vector.input[field]);
          assert.notStrictEqual(value, vector.input[field]);
        }
        if (temporal.uncertainty !== null) {
          assert.notStrictEqual(temporal.uncertainty, vector.input.temporal.uncertainty);
        }
      } else {
        keys(report, statusKeys);
        assert.equal(Object.hasOwn(report, 'pad'), false);
        assert.equal(Object.hasOwn(report, 'temporal'), false);
      }
    }
    assert.deepEqual(vector.input, before);

    const child = spawn(process.execPath, [cli], { stdio: ['pipe', 'pipe', 'pipe'] });
    t.after(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
    child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
    child.stdin.on('error', () => {});
    const completed = once(child, 'close');
    child.stdin.end(bytes);
    const [code, signal] = await completed;
    assert.equal(signal, null);
    assert.equal(code, vector.expected_cli_exit);
    assert.equal(stderr, '');
    assert.equal(stdout, `${JSON.stringify(vector.expected_status)}\n`);
    const status = JSON.parse(stdout);
    closed(status);
    assert.deepEqual(status, vector.expected_status);
  });
}
