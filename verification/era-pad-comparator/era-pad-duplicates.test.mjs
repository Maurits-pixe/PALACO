import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { compareEraPadJson, compareEraPadJsonForRequest } from './era-pad-json.mjs';

const corpus = JSON.parse(readFileSync(new URL('./era-pad-vectors.v0.1.json', import.meta.url), 'utf8'));
const base = corpus.vectors.find(vector => vector.id === 'synthetic-pass-known-time');
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
  ['', ['schema_version', 'classification', 'source_authenticity',
    'assessment_id', 'request_digest', 'pad', 'temporal']],
  ['pad', ['assessment_id', 'request_digest', 'observation_id',
    'raw_result', 'raw_result_sha256', 'normalized_result']],
  ['temporal', ['assessment_id', 'request_digest', 'source_kind',
    'observed_at', 'recorded_at', 'sync_status', 'uncertainty']],
  ['temporal.uncertainty', ['value', 'unit']],
];
const paths = layers.flatMap(([parent, fields]) => fields.map(key => parent ? `${parent}.${key}` : key));
const at = (value, path) => path ? path.split('.').reduce((object, key) => object[key], value) : value;
const escapeCharacter = character => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`;
const escapedFirstKey = key => `"${escapeCharacter(key[0])}${key.slice(1)}"`;
const escapedKey = key => `"${[...key].map(escapeCharacter).join('')}"`;

// Only trusted golden objects are traversed; duplicate members are emitted as text.
function serialize(input, { duplicate, reverse = false, whitespace = false, escapeNames = false } = {}) {
  let injections = 0;
  const space = whitespace ? ' \t\r\n ' : '';
  function walk(value, parent = '') {
    if (value === null || typeof value !== 'object') return JSON.stringify(value);
    const entries = Object.entries(value);
    if (reverse) entries.reverse();
    const members = entries.flatMap(([key, item]) => {
      const path = parent ? `${parent}.${key}` : key;
      const spelling = escapeNames ? escapedKey(key) : JSON.stringify(key);
      const original = `${spelling}:${space}${walk(item, path)}`;
      if (path !== duplicate?.path) return [original];
      injections++;
      const duplicateSpelling = duplicate.escaped ? escapedFirstKey(key) : JSON.stringify(key);
      const conflict = `${duplicateSpelling}:${space}true`;
      return duplicate.originalFirst ? [original, conflict] : [conflict, original];
    });
    return `{${space}${members.join(`,${space}`)}${space}}`;
  }
  const text = `${space}${walk(input)}${space}`;
  assert.equal(injections, duplicate ? 1 : 0);
  return text;
}

const mutations = paths.flatMap(path => [false, true].flatMap(escaped =>
  [false, true].map(originalFirst => ({ path, escaped, originalFirst }))));

test('duplicate matrix pins 22 exact paths and 88 spelling/order mutations', () => {
  assert.deepEqual(layers.map(([, fields]) => fields.length), [7, 6, 7, 2]);
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
  assert.equal(mutations.length, 88);
  assert.equal(new Set(mutations.map(mutation => JSON.stringify(mutation))).size, 88);
  assert.equal(base.input.assessment_id, matchingContext.assessment_id);
  assert.equal(base.input.request_digest, matchingContext.request_digest);
  assert.notEqual(base.input.assessment_id, mismatchingContext.assessment_id);
  assert.notEqual(base.input.request_digest, mismatchingContext.request_digest);
  assert.equal(invalid.reason, 'INVALID_INPUT');
  for (const [parent, fields] of layers) {
    assert.deepEqual(Object.keys(at(base.input, parent)).sort(), [...fields].sort());
  }
});

function duplicateDocument(mutation) {
  const text = serialize(base.input, { duplicate: mutation });
  // Native last-key-wins parsing verifies this fixture, never production acceptance.
  const parsed = JSON.parse(text);
  const expected = structuredClone(base.input);
  if (mutation.originalFirst) {
    const segments = mutation.path.split('.');
    const key = segments.pop();
    at(expected, segments.join('.'))[key] = true;
  }
  assert.notDeepEqual(at(base.input, mutation.path), true);
  assert.deepEqual(at(parsed, mutation.path),
    mutation.originalFirst ? true : at(base.input, mutation.path));
  assert.deepEqual(parsed, expected);
  return Buffer.from(text, 'utf8');
}

for (const mutation of mutations) {
  const { path, escaped, originalFirst } = mutation;
  test(`duplicate ${path}: ${escaped ? 'escaped-equivalent' : 'exact'}, ${originalFirst ? 'original/true' : 'true/original'}`, () => {
    const bytes = duplicateDocument(mutation);
    for (const report of [
      compareEraPadJson(bytes),
      compareEraPadJsonForRequest(bytes, matchingContext),
      compareEraPadJsonForRequest(bytes, mismatchingContext),
    ]) {
      assert.deepEqual(report, invalid);
      assert.equal(Object.hasOwn(report, 'pad'), false);
      assert.equal(Object.hasOwn(report, 'temporal'), false);
    }
  });
}

const representations = [
  ['ordinary no-duplicate', {}],
  ['recursively reversed', { reverse: true }],
  ['legal JSON whitespace', { whitespace: true }],
  ['every property name escaped', { escapeNames: true }],
  ['reversed, whitespace and escaped names', { reverse: true, whitespace: true, escapeNames: true }],
];
const validVectors = corpus.vectors.filter(vector => vector.structurally_valid);
test('representation controls pin 11 structurally valid goldens and five spellings', () => {
  assert.equal(validVectors.length, 11);
  assert.equal(representations.length, 5);
});

for (const vector of validVectors) {
  for (const [name, options] of representations) {
    test(`no-duplicate ${name}: ${vector.id}`, () => {
      const text = serialize(vector.input, options);
      assert.deepEqual(JSON.parse(text), vector.input);
      const bytes = Buffer.from(text, 'utf8');
      const expected = {
        ...vector.expected_status, pad: vector.input.pad, temporal: vector.input.temporal,
      };
      for (const report of [
        compareEraPadJson(bytes), compareEraPadJsonForRequest(bytes, matchingContext),
      ]) {
        assert.deepEqual(report, expected);
        assert.notEqual(report.reason, 'INVALID_INPUT');
        if (vector.id === 'synthetic-unicode-free-text') {
          assert.equal(report.pad.raw_result, 'Fictional café e\u0301 🙂');
          assert.equal(report.pad.raw_result_sha256, vector.input.pad.raw_result_sha256);
          assert.equal(createHash('sha256').update(report.pad.raw_result, 'utf8').digest('hex'),
            vector.input.pad.raw_result_sha256);
        }
      }
    });
  }
}

const cliPaths = ['assessment_id', 'pad.assessment_id', 'temporal.assessment_id', 'temporal.uncertainty.value'];
for (const [cliIndex, entrypoint] of ['era-pad-cli.mjs', 'era-pad-request-cli.mjs'].entries()) {
  for (const path of cliPaths) {
    for (const originalFirst of [false, true]) {
      // Pair spellings across entrypoints to bound the real-process matrix to 16.
      const escaped = originalFirst === (cliIndex === 0);
      test(`${entrypoint} duplicate ${path}: ${escaped ? 'escaped' : 'exact'}, ${originalFirst ? 'original/true' : 'true/original'}`,
        { timeout: 5000 }, async t => {
          const args = [fileURLToPath(new URL(`./${entrypoint}`, import.meta.url))];
          if (cliIndex === 1) args.push(mismatchingContext.assessment_id, mismatchingContext.request_digest);
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
          child.stdin.end(duplicateDocument({ path, escaped, originalFirst }));
          const [code, signal] = await completed;
          assert.deepEqual({ code, signal, stdout, stderr }, {
            code: 2, signal: null, stdout: `${JSON.stringify(invalid)}\n`, stderr: '',
          });
        });
    }
  }
}
