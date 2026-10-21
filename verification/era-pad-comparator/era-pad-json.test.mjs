import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { compareEraPad, SCHEMA_VERSION, MAX_INPUT_BYTES } from './era-pad-comparator.mjs';
import { compareEraPadJson } from './era-pad-json.mjs';

const invalid = compareEraPad(null);
const hash = raw => createHash('sha256').update(raw, 'utf8').digest('hex');
const cli = fileURLToPath(new URL('./era-pad-cli.mjs', import.meta.url));
function fixture(raw = 'PASS', normalized = raw) {
  return {
    schema_version: SCHEMA_VERSION, classification: 'SYNTHETIC_ONLY',
    source_authenticity: 'UNVERIFIED', assessment_id: 'private-fixture', request_digest: 'a'.repeat(64),
    pad: {
      assessment_id: 'private-fixture', request_digest: 'a'.repeat(64),
      observation_id: 'private-observation', raw_result: raw, raw_result_sha256: hash(raw),
      normalized_result: normalized,
    },
    temporal: {
      assessment_id: 'private-fixture', request_digest: 'a'.repeat(64),
      source_kind: 'SYNTHETIC_FIXTURE', observed_at: null, recorded_at: null,
      sync_status: 'UNKNOWN', uncertainty: { value: 0, unit: 'ms' },
    },
  };
}
const encode = input => Buffer.from(JSON.stringify(input));
const rejected = text => assert.deepEqual(compareEraPadJson(Buffer.from(text)), invalid);

test('byte-only entrypoint preserves the object API report and bounds actual view bytes', () => {
  const input = encode(fixture());
  assert.deepEqual(compareEraPadJson(input), compareEraPad(fixture()));
  assert.deepEqual(compareEraPadJson(new Uint8Array(input)), compareEraPad(fixture()));
  const backing = Buffer.concat([Buffer.from('bad'), input, Buffer.from('bad')]);
  assert.deepEqual(compareEraPadJson(backing.subarray(3, -3)), compareEraPad(fixture()));
  for (const value of [JSON.stringify(fixture()), {}, [], null, input.buffer, new Uint16Array(2)]) {
    assert.deepEqual(compareEraPadJson(value), invalid);
  }
  const spoofed = new Uint8Array(MAX_INPUT_BYTES + 1);
  Object.defineProperty(spoofed, 'byteLength', { value: 0 });
  assert.deepEqual(compareEraPadJson(spoofed), invalid);
});

test('fatal UTF-8, BOM and malformed Unicode are rejected without raw echoes', () => {
  for (const bytes of [
    [0xc0, 0xaf], [0xe2, 0x82], [0xed, 0xa0, 0x80], [0xff],
    [0xef, 0xbb, 0xbf, ...encode(fixture())],
  ]) assert.deepEqual(compareEraPadJson(Buffer.from(bytes)), invalid);
  const json = JSON.stringify(fixture());
  for (const raw of ['"\\ud800"', '"\\udc00"', '"\\ud800x"', '"\\udc00\\ud800"']) {
    rejected(json.replace('"PASS"', raw));
  }
  assert.deepEqual(compareEraPadJson(Buffer.concat([
    Buffer.from(json.slice(0, -1)), Buffer.from([0xff]), Buffer.from('}'),
  ])), invalid);
});

test('duplicates including escaped equivalent keys fail at each object level', () => {
  const json = JSON.stringify(fixture());
  for (const [key, replacement] of [
    ['"schema_version":', '"schema_version":null,"schema_versio\\u006e":'],
    ['"raw_result":', '"raw_result":null,"raw_resul\\u0074":'],
    ['"source_kind":', '"source_kind":null,"source_kin\\u0064":'],
    ['"value":', '"value":1,"\\u0076alue":'],
    ['"unit":', '"unit":"s","unit":'],
  ]) rejected(json.replace(key, replacement));
  rejected('{"__proto__":1,"\\u005f_proto__":2}');
});

test('strict grammar rejects roots, arrays, depth, bad numbers and trailing syntax', () => {
  for (const text of [
    '', ' ', 'null', 'true', '1', '"text"', '[]', '[{}]', '{}{}', '{} null',
    '{}//comment', '/*comment*/{}', '{"x":}', '{"x":1,}', '{"x":01}', '{"x":+1}',
    '{"x":.1}', '{"x":1.}', '{"x":1e}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}',
    '{"x":-1e999}', '{"x":"\\x20"}', '{"x":"\n"}', '{"x":"unterminated}',
    '{"x":[1]}', '{"x":{"y":{"z":{}}}}', '{'.repeat(MAX_INPUT_BYTES),
    '{"x":true false}', '{"x":undefined}', '{"x":1}\u00a0',
  ]) rejected(text);
  const input = fixture();
  input.temporal.uncertainty.value = -0;
  rejected(JSON.stringify(input).replace('"value":0', '"value":-0'));
  for (const value of [[], { value: { nested: 0 }, unit: 'ms' }]) {
    input.temporal.uncertainty = value;
    assert.deepEqual(compareEraPadJson(encode(input)), invalid);
  }
});

test('unknown and authority fields still use existing closed schema validation', () => {
  for (const component of [null, 'pad', 'temporal', 'uncertainty']) {
    const input = fixture();
    const target = component === null ? input
      : component === 'uncertainty' ? input.temporal.uncertainty : input[component];
    target.operativeAuthority = 'OPEN';
    assert.deepEqual(compareEraPadJson(encode(input)), invalid);
  }
});

test('incoming 16384-byte boundary includes whitespace; one extra byte fails', () => {
  const json = encode(fixture());
  const exact = Buffer.concat([json, Buffer.alloc(MAX_INPUT_BYTES - json.length, ' ')]);
  assert.equal(exact.length, MAX_INPUT_BYTES);
  assert.equal(compareEraPadJson(exact).result, 'CONSISTENT_SYNTHETIC_ONLY');
  assert.deepEqual(compareEraPadJson(Buffer.concat([exact, Buffer.from(' ')])), invalid);
});

test('decoded raw Unicode and escaped forms hash original UTF-8 without normalization', () => {
  for (const raw of ['é', 'e\u0301', '🙂', ' PASS\n', '\0', '\ufeff']) {
    const input = fixture(raw, 'UNKNOWN');
    const json = JSON.stringify(input);
    const report = compareEraPadJson(Buffer.from(json));
    assert.equal(report.result, 'CONSISTENT_SYNTHETIC_ONLY');
    assert.equal(report.pad.raw_result, raw);
    assert.equal(report.pad.raw_result_sha256, hash(raw));
    input.pad.raw_result_sha256 = hash(raw + ' ');
    assert.equal(compareEraPadJson(encode(input)).result, 'INTEGRITY_MISMATCH');
  }
  const input = fixture('🙂', 'UNKNOWN');
  const escaped = JSON.stringify(input).replace('🙂', '\\ud83d\\ude42');
  assert.deepEqual(compareEraPadJson(Buffer.from(escaped)), compareEraPad(input));
  assert.notEqual(hash('é'), hash('e\u0301'));
});

function launch(args = [], source = cli) {
  const child = spawn(process.execPath, source === cli ? [cli, ...args] : ['--input-type=module', '-e', source], {
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  let stdout = '';
  let stderr = '';
  child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
  child.stdin.on('error', () => {});
  const result = once(child, 'close').then(([code, signal]) => ({ code, signal, stdout, stderr }));
  return { child, result };
}
function statusOnly(result, code) {
  assert.equal(result.code, code);
  assert.equal(result.signal, null);
  assert.equal(result.stderr, '');
  const report = JSON.parse(result.stdout);
  assert.equal(report.disposition, 'HOLD');
  assert.equal(report.operativeAuthority, 'NONE');
  assert.equal(Object.hasOwn(report, 'pad'), false);
  assert.equal(Object.hasOwn(report, 'temporal'), false);
  for (const value of ['private-fixture', 'private-observation', 'a'.repeat(64), cli]) {
    assert.equal(result.stdout.includes(value), false);
  }
  return report;
}

test('fresh CLI processes emit status only; negative PAD codes can exit zero, never grant permission', async () => {
  for (const code of ['PASS', 'FAIL', 'ERROR', 'TIMEOUT', 'UNKNOWN']) {
    const { child, result } = launch();
    child.stdin.end(encode(fixture(code)));
    const report = statusOnly(await result, 0);
    assert.equal(report.result, 'CONSISTENT_SYNTHETIC_ONLY');
    assert.equal(report.pad_status, code);
    assert.equal(report.canOpenContact, false);
  }
  const input = fixture();
  input.pad.raw_result_sha256 = '0'.repeat(64);
  const { child, result } = launch();
  child.stdin.end(encode(input));
  assert.equal(statusOnly(await result, 2).reason, 'INTEGRITY_MISMATCH');
});

test('CLI rejects args, empty/bad/oversize bytes with exactly the sanitized diagnostic', async () => {
  for (const [args, bytes] of [
    [['--raw'], encode(fixture())], [['private/path.json'], encode(fixture())],
    [[], Buffer.alloc(0)], [[], Buffer.from([0xff])],
    [[], Buffer.from('{"private":"raw fixture"')], [[], Buffer.alloc(MAX_INPUT_BYTES + 1, ' ')],
  ]) {
    const { child, result } = launch(args);
    child.stdin.end(bytes);
    assert.deepEqual(statusOnly(await result, 2), invalid);
  }
  const { child, result } = launch();
  const json = encode(fixture());
  child.stdin.end(Buffer.concat([json, Buffer.alloc(MAX_INPUT_BYTES - json.length, ' ')]));
  assert.equal(statusOnly(await result, 0).result, 'CONSISTENT_SYNTHETIC_ONLY');
});

test('CLI destroys oversize open stdin and terminates without waiting for EOF', { timeout: 6000 }, async t => {
  const { child, result } = launch();
  t.after(() => { if (child.exitCode === null) child.kill(); });
  child.stdin.write(Buffer.alloc(MAX_INPUT_BYTES + 1, ' '));
  assert.deepEqual(statusOnly(await result, 2), invalid);
});

test('fixed deadline rejects actual open stdin, even complete JSON without EOF, and terminates', { timeout: 7000 }, async t => {
  const started = performance.now();
  const { child, result } = launch();
  t.after(() => { if (child.exitCode === null) child.kill(); });
  child.stdin.write(encode(fixture()));
  const heartbeat = setInterval(() => { child.stdin.write(' '); }, 100);
  t.after(() => clearInterval(heartbeat));
  assert.deepEqual(statusOnly(await result, 2), invalid);
  assert.ok(performance.now() - started >= 1900);
  assert.ok(performance.now() - started < 6000);
});

test('CLI stream acquisition errors and premature close use sanitized failure', async () => {
  for (const action of ["input.destroy(new Error('private-error'))", 'input.destroy()']) {
    const script = `
      import { PassThrough } from 'node:stream';
      import { main } from ${JSON.stringify(new URL('./era-pad-cli.mjs', import.meta.url).href)};
      const input = new PassThrough();
      Object.defineProperty(process, 'stdin', { value: input });
      process.argv = [process.execPath, ${JSON.stringify(cli)}];
      const done = main();
      ${action};
      await done;
    `;
    const { child, result } = launch([], script);
    child.stdin.end();
    assert.deepEqual(statusOnly(await result, 2), invalid);
  }
});

test('importing CLI does not read stdin, print, set exit status or install timers', async () => {
  const script = `
    import assert from 'node:assert/strict';
    const listeners = process.stdin.eventNames().map(name => [name, process.stdin.listenerCount(name)]);
    const exitCode = process.exitCode;
    globalThis.setTimeout = () => { throw new Error('unexpected timer'); };
    await import(${JSON.stringify(new URL('./era-pad-cli.mjs', import.meta.url).href)});
    assert.deepEqual(process.stdin.eventNames().map(name => [name, process.stdin.listenerCount(name)]), listeners);
    assert.equal(process.stdin.readableFlowing, null);
    assert.equal(process.exitCode, exitCode);
  `;
  const { child, result } = launch([], script);
  child.stdin.end();
  assert.deepEqual(await result, { code: 0, signal: null, stdout: '', stderr: '' });
});
