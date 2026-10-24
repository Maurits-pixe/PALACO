import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { compareEraPad } from './era-pad-comparator.mjs';
import { compareEraPadJson, compareEraPadJsonForRequest } from './era-pad-json.mjs';

const corpus = JSON.parse(readFileSync(new URL('./era-pad-vectors.v0.1.json', import.meta.url), 'utf8'));
const base = corpus.vectors[0];
const original = structuredClone(base);
const invalid = corpus.vectors.find(vector => vector.id === 'synthetic-extra-authority-sanitized').expected_status;
const matchingContext = {
  assessment_id: 'fictional-assessment',
  request_digest: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
};
const mismatchingContext = {
  assessment_id: 'independent-host-assessment',
  request_digest: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
};
const layers = [
  ['root', '', ['schema_version', 'classification', 'source_authenticity',
    'assessment_id', 'request_digest', 'pad', 'temporal']],
  ['pad', 'pad', ['assessment_id', 'request_digest', 'observation_id',
    'raw_result', 'raw_result_sha256', 'normalized_result']],
  ['temporal', 'temporal', ['assessment_id', 'request_digest', 'source_kind',
    'observed_at', 'recorded_at', 'sync_status', 'uncertainty']],
  ['uncertainty', 'temporal.uncertainty', ['value', 'unit']],
];
const at = (input, path) => path ? path.split('.').reduce((value, key) => value[key], input) : input;

test('schema matrix pins all 22 exact field paths and 48 distinct mutations', () => {
  assert.equal(base.id, 'synthetic-pass-known-time');
  assert.deepEqual(base.input.assessment_id, matchingContext.assessment_id);
  assert.deepEqual(base.input.request_digest, matchingContext.request_digest);
  assert.deepEqual(layers.map(([, , fields]) => fields.length), [7, 6, 7, 2]);
  const paths = layers.flatMap(([, path, fields]) => fields.map(field => path ? `${path}.${field}` : field));
  assert.deepEqual(paths, [
    'schema_version', 'classification', 'source_authenticity', 'assessment_id',
    'request_digest', 'pad', 'temporal',
    'pad.assessment_id', 'pad.request_digest', 'pad.observation_id', 'pad.raw_result',
    'pad.raw_result_sha256', 'pad.normalized_result',
    'temporal.assessment_id', 'temporal.request_digest', 'temporal.source_kind',
    'temporal.observed_at', 'temporal.recorded_at', 'temporal.sync_status',
    'temporal.uncertainty', 'temporal.uncertainty.value', 'temporal.uncertainty.unit',
  ]);
  assert.equal(paths.length, 22);
  assert.equal(new Set(paths).size, 22);
  const mutations = paths.flatMap(path => [`delete:${path}`, `wrong-type:${path}`]);
  mutations.push(...layers.map(([, path]) => `extra:${path || 'root'}`));
  assert.equal(mutations.length, 48);
  assert.equal(new Set(mutations).size, 48);
  for (const [, path, fields] of layers) {
    assert.deepEqual(Object.keys(at(base.input, path)).sort(), [...fields].sort());
  }
});

function checkApis(input, expected, includeMismatch = false) {
  const before = structuredClone(input);
  const bytes = Buffer.from(JSON.stringify(input));
  const bytesBefore = Buffer.from(bytes);
  const contexts = [matchingContext, mismatchingContext];
  const contextsBefore = structuredClone(contexts);
  const calls = [
    () => compareEraPad(input),
    () => compareEraPadJson(bytes),
    () => compareEraPadJsonForRequest(bytes, matchingContext),
  ];
  if (includeMismatch) calls.push(() => compareEraPadJsonForRequest(bytes, mismatchingContext));
  for (const call of calls) {
    assert.deepEqual(call(), expected);
    assert.deepEqual(input, before);
    assert.deepEqual(bytes, bytesBefore);
    assert.deepEqual(contexts, contextsBefore);
    assert.deepEqual(base, original);
  }
}

for (const [layer, path, fields] of layers) {
  for (const mutation of ['deleted', 'wrong type', 'extra key']) {
    test(`${layer} schema: ${mutation} is sanitized before host binding`, () => {
      for (const field of mutation === 'extra key' ? ['private_extra_field'] : fields) {
        const input = structuredClone(base.input);
        const target = at(input, path);
        if (mutation === 'deleted') delete target[field];
        else target[field] = true;
        // Boolean is invalid even for nullable times, uncertainty and numeric value.
        checkApis(input, invalid, true);
      }
    });
  }
}

test('nullable times and uncertainty remain valid independently and in every combination', () => {
  const controls = [
    ['observed_at'], ['recorded_at'], ['uncertainty'],
    ['observed_at', 'recorded_at'], ['observed_at', 'uncertainty'],
    ['recorded_at', 'uncertainty'], ['observed_at', 'recorded_at', 'uncertainty'],
  ];
  for (const fields of controls) {
    const input = structuredClone(base.input);
    for (const field of fields) input.temporal[field] = null;
    checkApis(input, {
      ...base.expected_status, temporal_status: 'UNKNOWN',
      pad: structuredClone(input.pad), temporal: structuredClone(input.temporal),
    });
  }
});

test('empty raw_result is valid with the literal empty-string SHA-256 and UNKNOWN normalization', () => {
  const input = structuredClone(base.input);
  input.pad.raw_result = '';
  input.pad.raw_result_sha256 = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
  input.pad.normalized_result = 'UNKNOWN';
  checkApis(input, {
    ...base.expected_status, pad_status: 'UNKNOWN',
    pad: structuredClone(input.pad), temporal: structuredClone(input.temporal),
  });
});

for (const [layer, path] of layers) {
  for (const entrypoint of ['era-pad-cli.mjs', 'era-pad-request-cli.mjs']) {
    test(`${entrypoint} sanitizes representative ${layer} schema mutation`,
      { timeout: 5000 }, async t => {
        const input = structuredClone(base.input);
        at(input, path).private_extra_field = 'private-schema-payload';
        const before = structuredClone(input);
        const bytes = Buffer.from(JSON.stringify(input));
        const bytesBefore = Buffer.from(bytes);
        const args = [fileURLToPath(new URL(`./${entrypoint}`, import.meta.url))];
        if (entrypoint === 'era-pad-request-cli.mjs') {
          // Independently fixed, valid mismatching context; never read from input.
          args.push('independent-host-assessment',
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb');
        }
        const child = spawn(process.execPath, args, { stdio: ['pipe', 'pipe', 'pipe'] });
        t.after(() => {
          if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
        });
        child.stdin.on('error', () => {});
        let stdout = '';
        let stderr = '';
        child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
        child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
        const completed = once(child, 'close');
        child.stdin.end(bytes);
        const [code, signal] = await completed;
        assert.deepEqual({ code, signal, stdout, stderr }, {
          code: 2, signal: null, stdout: `${JSON.stringify(invalid)}\n`, stderr: '',
        });
        assert.deepEqual(input, before);
        assert.deepEqual(bytes, bytesBefore);
        assert.deepEqual(base, original);
      });
  }
}
