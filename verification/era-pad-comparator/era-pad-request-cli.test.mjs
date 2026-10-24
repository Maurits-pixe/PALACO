import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const cli = new URL('./era-pad-request-cli.mjs', import.meta.url);
const runner = new URL('./era-pad-cli.mjs', import.meta.url);
const corpus = JSON.parse(readFileSync(new URL('./era-pad-vectors.v0.1.json', import.meta.url), 'utf8'));
const base = corpus.vectors[0];
const invalid = corpus.vectors.find(vector => vector.expected_status.reason === 'INVALID_INPUT').expected_status;
const refs = input => [input.assessment_id, input.request_digest];
const line = status => `${JSON.stringify(status)}\n`;

function launch(t, args) {
  const child = spawn(process.execPath, args, { stdio: ['pipe', 'pipe', 'pipe'] });
  t.after(() => {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  });
  child.stdin.on('error', () => {});
  let stdout = '';
  let stderr = '';
  child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
  const completed = once(child, 'close').then(([code, signal]) => ({ code, signal, stdout, stderr }));
  return { child, completed };
}

async function check(completed, status, exit = 2) {
  const result = await completed;
  assert.equal(result.signal, null);
  assert.equal(result.code, exit);
  assert.equal(result.stderr, '');
  assert.equal(result.stdout, line(status));
}

for (const vector of corpus.vectors) {
  test(`request CLI matches golden status with matching root context: ${vector.id}`,
    { timeout: 5000 }, async t => {
      const { child, completed } = launch(t, [fileURLToPath(cli), ...refs(vector.input)]);
      child.stdin.end(JSON.stringify(vector.input));
      await check(completed, vector.expected_status, vector.expected_cli_exit);
    });
}

for (const [field, value] of [['assessment_id', 'different-synthetic-request'], ['request_digest', '0'.repeat(64)]]) {
  test(`request CLI rejects coherent all-component substitution of ${field}`,
    { timeout: 5000 }, async t => {
      const input = structuredClone(base.input);
      for (const part of [input, input.pad, input.temporal]) part[field] = value;
      const { child, completed } = launch(t, [fileURLToPath(cli), ...refs(base.input)]);
      child.stdin.end(JSON.stringify(input));
      await check(completed, {
        ...base.expected_status, result: 'REJECTED', reason: 'BINDING_MISMATCH', binding_status: 'MISMATCH',
      });
    });
}

for (const [name, bytes] of [
  ['malformed JSON', '{"assessment_id":"different-synthetic-request",'],
  ['malformed schema', JSON.stringify({ ...base.input, assessment_id: 'different-synthetic-request', extra: true })],
]) {
  test(`request CLI sanitizes ${name} before mismatching context`, { timeout: 5000 }, async t => {
    const { child, completed } = launch(t, [fileURLToPath(cli), 'other-host-context', '0'.repeat(64)]);
    child.stdin.end(bytes);
    await check(completed, invalid);
  });
}

const [id, digest] = refs(base.input);
const badArgs = [
  ['absent', []], ['missing digest', [id]], ['extra', [id, digest, 'extra-private-path']],
  ['flag', ['--help']], ['option', ['--assessment-id', id, digest]],
  ['empty ID', ['', digest]], ['empty digest', [id, '']],
  ['long ID', ['x'.repeat(129), digest]], ['space ID', ['private ID', digest]],
  ['path ID', ['/private/path', digest]], ['non-ASCII ID', ['é', digest]],
  ['control ID', ['private\nID', digest]], ['tab ID', ['private\tID', digest]],
  ['short digest', [id, 'a'.repeat(63)]], ['long digest', [id, 'a'.repeat(65)]],
  ['invalid digest', [id, 'g'.repeat(64)]], ['uppercase digest', [id, 'A'.repeat(64)]],
  ['control digest', [id, `${'a'.repeat(63)}\n`]],
  ['trailing digest control', [id, `${'a'.repeat(64)}\n`]],
  ['non-ASCII digest', [id, `${'a'.repeat(63)}é`]],
];
for (const [name, args] of badArgs) {
  test(`request CLI immediately rejects ${name} arguments without EOF`,
    { timeout: 1800 }, async t => {
      const { child, completed } = launch(t, [fileURLToPath(cli), ...args]);
      assert.equal(child.stdin.writableEnded, false);
      await check(completed, invalid);
      assert.equal(child.stdin.writableEnded, false);
    });
}

test('invalid invocation destroys stdin synchronously before acquiring bytes',
  { timeout: 5000 }, async t => {
    const { completed } = launch(t, ['--input-type=module', '-e', `
      import assert from 'node:assert/strict';
      import { PassThrough, Writable } from 'node:stream';
      import { mainForRequest } from ${JSON.stringify(runner.href)};
      const cases = ${JSON.stringify([...badArgs.map(([, args]) => args),
        ['private\0ID', digest], [id, `${'a'.repeat(63)}\0`]])};
      let writes = 0;
      const output = new Writable({
        write(chunk, encoding, done) {
          writes++;
          assert.equal(chunk.toString(), ${JSON.stringify(line(invalid))});
          done();
        },
      });
      Object.defineProperty(process, 'stdout', { value: output });
      for (const args of cases) {
        const input = new PassThrough();
        input.on('data', () => assert.fail('invalid invocation must not read'));
        Object.defineProperty(process, 'stdin', { value: input, configurable: true });
        process.argv = [process.execPath, ${JSON.stringify(fileURLToPath(cli))}, ...args];
        const done = mainForRequest();
        assert.equal(input.destroyed, true);
        assert.equal(input.writableEnded, false);
        await done;
        assert.equal(process.exitCode, 2);
      }
      assert.equal(writes, cases.length);
    `]);
    const result = await completed;
    assert.deepEqual(result, { code: 2, signal: null, stdout: '', stderr: '' });
  });

for (const assessmentId of ['x', 'x'.repeat(128), 'AZaz09._:-']) {
  test(`request CLI accepts ID syntax boundary ${assessmentId.length}`,
    { timeout: 5000 }, async t => {
      const input = structuredClone(base.input);
      for (const part of [input, input.pad, input.temporal]) part.assessment_id = assessmentId;
      const { child, completed } = launch(t, [fileURLToPath(cli), ...refs(input)]);
      child.stdin.end(JSON.stringify(input));
      await check(completed, base.expected_status, 0);
    });
}

test('request wrapper import has no stream or process side effects', { timeout: 5000 }, async t => {
  const { completed } = launch(t, ['--input-type=module', '-e', `
    import assert from 'node:assert/strict';
    process.argv = [process.execPath, 'fictional-importer', 'invalid-private-argument'];
    const input = process.stdin;
    const output = process.stdout;
    const events = ['data', 'end', 'close', 'error'];
    const before = events.map(event => input.listeners(event));
    const outputBefore = events.map(event => output.listeners(event));
    const exit = process.exitCode;
    let writes = 0;
    output.write = () => { writes++; return true; };
    await import(${JSON.stringify(cli.href)});
    assert.equal(writes, 0);
    assert.equal(input.destroyed, false);
    assert.equal(input.readableFlowing, null);
    assert.equal(process.exitCode, exit);
    assert.deepEqual(events.map(event => input.listeners(event)), before);
    assert.deepEqual(events.map(event => output.listeners(event)), outputBefore);
  `]);
  const result = await completed;
  assert.deepEqual(result, { code: 0, signal: null, stdout: '', stderr: '' });
});

test('request CLI applies actual two-second input deadline with valid context and no EOF',
  { timeout: 6000 }, async t => {
    const start = performance.now();
    const { child, completed } = launch(t, [fileURLToPath(cli), id, digest]);
    child.stdin.write(JSON.stringify(base.input));
    await check(completed, invalid);
    assert.ok(performance.now() - start >= 1950);
    assert.equal(child.stdin.writableEnded, false);
  });

test('request CLI rejects more than 16384 bytes without EOF', { timeout: 1800 }, async t => {
  const { child, completed } = launch(t, [fileURLToPath(cli), id, digest]);
  child.stdin.write(Buffer.alloc(16385, ' '));
  await check(completed, invalid);
  assert.equal(child.stdin.writableEnded, false);
});

for (const mode of ['acknowledged', 'error', 'stalled']) {
  test(`mainForRequest shares bounded ${mode} output lifecycle`,
    { timeout: 6000 }, async t => {
      const expectedExit = mode === 'acknowledged' ? 0 : 2;
      const { completed } = launch(t, ['--input-type=module', '-e', `
        import assert from 'node:assert/strict';
        import { Readable, Writable } from 'node:stream';
        import { setImmediate as turn } from 'node:timers/promises';
        import { mainForRequest } from ${JSON.stringify(runner.href)};
        process.argv = [process.execPath, ${JSON.stringify(fileURLToPath(cli))},
          ${JSON.stringify(id)}, ${JSON.stringify(digest)}];
        const input = Readable.from([Buffer.from(${JSON.stringify(JSON.stringify(base.input))})]);
        let writes = 0;
        let callback;
        const output = new Writable({
          write(chunk, encoding, done) {
            writes++;
            assert.equal(process.exitCode, 2);
            assert.equal(chunk.toString(), ${JSON.stringify(line(base.expected_status))});
            callback = done;
          },
        });
        Object.defineProperty(process, 'stdin', { value: input });
        Object.defineProperty(process, 'stdout', { value: output });
        const start = performance.now();
        let settled = false;
        const done = mainForRequest().then(() => { settled = true; });
        await turn();
        assert.equal(settled, false);
        assert.equal(process.exitCode, 2);
        assert.equal(writes, 1);
        const mode = ${JSON.stringify(mode)};
        if (mode === 'acknowledged') callback();
        if (mode === 'error') callback(new Error('private-output-path-and-token'));
        await done;
        await turn();
        assert.equal(input.destroyed, true);
        assert.equal(process.exitCode, ${expectedExit});
        assert.equal(writes, 1);
        if (mode === 'stalled') assert.ok(performance.now() - start >= 1950);
        if (mode !== 'acknowledged') {
          assert.equal(output.destroyed, true);
          output.emit('error', new Error('private-late-output-error'));
        }
      `]);
      const result = await completed;
      assert.deepEqual(result, { code: expectedExit, signal: null, stdout: '', stderr: '' });
    });
}
