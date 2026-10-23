import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const corpus = JSON.parse(readFileSync(new URL('./era-pad-vectors.v0.1.json', import.meta.url), 'utf8'));
const unicode = corpus.vectors.find(vector => vector.id === 'synthetic-unicode-free-text');
const invalid = corpus.vectors.find(vector => vector.id === 'synthetic-extra-authority-sanitized');
const cli = new URL('./era-pad-cli.mjs', import.meta.url);
const json = Buffer.from(JSON.stringify(unicode.input));
const budget = 16384;

function splitRange(bytes, start, length) {
  assert.ok(start > 0);
  assert.ok(start + length < bytes.length);
  return [
    bytes.subarray(0, start),
    ...Array.from(bytes.subarray(start, start + length), byte => Buffer.from([byte])),
    bytes.subarray(start + length),
  ];
}

async function run(t, chunks, terminal, vector = unicode) {
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every(chunk => chunk.length > 0));
  const script = `
    import assert from 'node:assert/strict';
    import { PassThrough } from 'node:stream';
    import { setImmediate as turn } from 'node:timers/promises';
    import { main } from ${JSON.stringify(cli.href)};
    const chunks = ${JSON.stringify(chunks.map(chunk => chunk.toString('base64')))}
      .map(chunk => Buffer.from(chunk, 'base64'));
    const input = new PassThrough();
    const seen = [];
    let ended = false;
    input.on('data', chunk => { seen.push(Buffer.from(chunk)); });
    input.on('end', () => { ended = true; });
    Object.defineProperty(process, 'stdin', { value: input });
    process.argv = [process.execPath, ${JSON.stringify(fileURLToPath(cli))}];
    let settled = false;
    const done = main().then(() => { settled = true; });
    for (let index = 0; index < chunks.length; index++) {
      // Scheduled writes to a flowing standard stream cannot coalesce in an OS pipe.
      await turn();
      assert.equal(settled, false);
      input.write(chunks[index]);
      assert.equal(seen.length, index + 1);
      assert.deepEqual(seen[index], chunks[index]);
    }
    await turn();
    const terminal = ${JSON.stringify(terminal)};
    if (terminal === 'overflow') {
      assert.equal(settled, true);
      assert.equal(ended, false);
      assert.equal(input.readableEnded, false);
      assert.equal(input.writableEnded, false);
    } else {
      assert.equal(settled, false);
      assert.equal(ended, false);
      if (terminal === 'error') input.destroy(new Error('fictional-private-stream-failure'));
      else if (terminal === 'close') input.destroy();
      else input.end();
    }
    await done;
    assert.equal(input.destroyed, true);
    assert.equal(seen.length, chunks.length);
    assert.equal(ended, terminal === 'end');
  `;
  const child = spawn(process.execPath, ['--input-type=module', '-e', script], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(() => {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  });
  let stdout = '';
  let stderr = '';
  child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
  const [code, signal] = await once(child, 'close');
  assert.equal(signal, null);
  assert.equal(stderr, '');
  assert.equal(code, vector.expected_cli_exit);
  assert.equal(stdout, `${JSON.stringify(vector.expected_status)}\n`);
  for (const value of [
    unicode.input.assessment_id, unicode.input.request_digest,
    unicode.input.pad.observation_id, unicode.input.pad.raw_result,
    unicode.input.pad.raw_result_sha256, fileURLToPath(cli),
    'fictional-private-stream-failure',
  ]) assert.equal(stdout.includes(value), false);
}

test('CLI reassembles every raw_result UTF-8 byte, including the four-byte emoji', { timeout: 5000 }, async t => {
  const raw = Buffer.from(unicode.input.pad.raw_result);
  assert.ok(raw.includes(Buffer.from([0xf0, 0x9f, 0x99, 0x82])));
  await run(t, splitRange(json, json.indexOf(raw), raw.length), 'end');
});

test('CLI reassembles JSON escape introducers and split escaped surrogate pairs', { timeout: 5000 }, async t => {
  const escaped = 'Fictional caf\\u00e9 e\\u0301 \\ud83d\\ude42';
  const bytes = Buffer.from(json.toString('utf8').replace(unicode.input.pad.raw_result, escaped));
  await run(t, splitRange(bytes, bytes.indexOf(escaped), escaped.length), 'end');
});

test('CLI reassembles an escaped literal backslash split between its two bytes', { timeout: 5000 }, async t => {
  const input = structuredClone(unicode.input);
  input.pad.raw_result += '\\';
  input.pad.raw_result_sha256 = 'a9f23e0bf8da80e81bc228f055d83d6531ffea9a3c6ca0cef126d6c1a1c4f04c';
  const bytes = Buffer.from(JSON.stringify(input));
  const start = bytes.indexOf(Buffer.from('\\\\'));
  await run(t, splitRange(bytes, start, 2), 'end');
});

test('CLI accepts exactly 16384 cumulative incoming bytes in separate chunks at EOF', { timeout: 5000 }, async t => {
  const chunks = [json, Buffer.alloc(7000, ' '), Buffer.alloc(budget - json.length - 7000, ' ')];
  assert.equal(chunks.reduce((size, chunk) => size + chunk.length, 0), budget);
  await run(t, chunks, 'end');
});

test('CLI rejects one extra chunk beyond 16384 cumulative bytes without EOF', { timeout: 5000 }, async t => {
  const chunks = [json, Buffer.alloc(budget - json.length, ' '), Buffer.from(' ')];
  assert.ok(chunks.every(chunk => chunk.length <= budget));
  assert.equal(chunks.reduce((size, chunk) => size + chunk.length, 0), budget + 1);
  await run(t, chunks, 'overflow', invalid);
});

test('CLI sanitizes incomplete multibyte UTF-8 at EOF after separated bytes', { timeout: 5000 }, async t => {
  const emoji = json.indexOf(Buffer.from('🙂'));
  assert.ok(emoji > 0);
  await run(t, [
    json.subarray(0, emoji), Buffer.from([0xf0]), Buffer.from([0x9f, 0x99]),
  ], 'end', invalid);
});

test('CLI sanitizes well-formed UTF-8 with truncated JSON at EOF', { timeout: 5000 }, async t => {
  await run(t, [json.subarray(0, 100), json.subarray(100, -1)], 'end', invalid);
});

test('CLI does not accept complete JSON before a subsequent underlying stream failure', { timeout: 5000 }, async t => {
  await run(t, [json.subarray(0, 100), json.subarray(100)], 'error', invalid);
});

test('CLI sanitizes premature stream close after partial bytes without EOF', { timeout: 5000 }, async t => {
  await run(t, [json.subarray(0, 50), json.subarray(50, 100)], 'close', invalid);
});
