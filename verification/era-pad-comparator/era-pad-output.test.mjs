import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const cli = new URL('./era-pad-cli.mjs', import.meta.url);
const corpus = JSON.parse(readFileSync(new URL('./era-pad-vectors.v0.1.json', import.meta.url), 'utf8'));
const vector = corpus.vectors.find(item => item.id === 'synthetic-pass-known-time');
const line = `${JSON.stringify(vector.expected_status)}\n`;

function childProcess(t, script, stdin = 'ignore') {
  const child = spawn(process.execPath, ['--input-type=module', '-e', script], {
    stdio: [stdin, 'pipe', 'pipe'],
  });
  t.after(() => {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  });
  return child;
}

async function injected(t, setup, checks, expected = 2) {
  const child = childProcess(t, `
    import assert from 'node:assert/strict';
    import { Readable, Writable } from 'node:stream';
    import { setImmediate as turn, setTimeout as delay } from 'node:timers/promises';
    import { main } from ${JSON.stringify(cli.href)};
    const expectedLine = ${JSON.stringify(line)};
    const secret = 'fictional-sensitive-output-error-token-and-path';
    let nativeWrites = 0;
    const nativeOutput = process.stdout;
    const nativeWrite = nativeOutput.write;
    nativeOutput.write = function (...args) {
      nativeWrites++;
      return nativeWrite.apply(this, args);
    };
    let writes = 0;
    const chunks = [];
    let callback;
    const output = new Writable({
      autoDestroy: false,
      write(chunk, encoding, done) {
        assert.equal(process.exitCode, 2);
        writes++;
        chunks.push(chunk.toString());
        callback = done;
      },
    });
    ${setup}
    Object.defineProperty(process, 'stdin', {
      value: Readable.from([Buffer.from(${JSON.stringify(JSON.stringify(vector.input))})]),
    });
    Object.defineProperty(process, 'stdout', { value: output });
    process.argv = [process.execPath, ${JSON.stringify(fileURLToPath(cli))}];
    let settled = false;
    const done = main().then(() => { settled = true; });
    await turn();
    ${checks}
    await done;
    await turn();
    assert.equal(settled, true);
    assert.equal(process.exitCode, ${expected});
    assert.equal(nativeWrites, 0);
    assert.ok(writes <= 1);
    assert.ok(chunks.every(chunk => chunk === expectedLine));
  `);
  let stdout = '';
  let stderr = '';
  child.stdout.setEncoding('utf8').on('data', chunk => { stdout += chunk; });
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
  const [code, signal] = await once(child, 'close');
  assert.equal(signal, null);
  assert.equal(stderr, '');
  assert.equal(stdout, '');
  assert.equal(code, expected);
}

test('output waits for delayed local acknowledgement, writes exactly once and removes only owned listeners',
  { timeout: 5000 }, async t => {
    await injected(t, `
      const unrelated = () => {};
      output.on('error', unrelated);
    `, `
      assert.equal(writes, 1);
      assert.equal(settled, false);
      assert.equal(process.exitCode, 2);
      await delay(40);
      assert.equal(settled, false);
      assert.equal(nativeWrites, 0);
      assert.deepEqual(chunks, [expectedLine]);
      callback();
      await done;
      assert.equal(output.destroyed, false);
      assert.deepEqual(output.listeners('error'), [unrelated]);
      assert.equal(output.listenerCount('close'), 0);
    `, 0);
  });

test('callback errors and subsequent asynchronous errors never expose sensitive stacks',
  { timeout: 5000 }, async t => {
    await injected(t, '', `
      callback(new Error(secret));
      await done;
      await turn();
      assert.equal(output.destroyed, true);
      output.emit('error', new Error(secret));
      await turn();
      output.emit('error', new Error(secret));
    `);
  });

test('synchronous output write throw fails closed without retry',
  { timeout: 5000 }, async t => {
    await injected(t, `
      output.write = () => { writes++; throw new Error(secret); };
    `, `
      await done;
      assert.equal(writes, 1);
      assert.equal(output.destroyed, true);
      output.emit('error', new Error(secret));
    `);
  });

test('premature close before callback fails closed even if callback later succeeds',
  { timeout: 5000 }, async t => {
    await injected(t, '', `
      assert.equal(settled, false);
      output.emit('close');
      await done;
      callback();
      assert.equal(output.destroyed, true);
    `);
  });

test('pre-destroyed output is not written and absorbs later errors',
  { timeout: 5000 }, async t => {
    await injected(t, `
      output.destroy();
    `, `
      await done;
      assert.equal(writes, 0);
      assert.equal(output.destroyed, true);
      output.emit('error', new Error(secret));
    `);
  });

test('ended nonwritable output is not written',
  { timeout: 5000 }, async t => {
    await injected(t, `
      output.end();
      assert.equal(output.writable, false);
      assert.equal(output.destroyed, false);
    `, `
      await done;
      assert.equal(writes, 0);
      assert.equal(output.destroyed, true);
    `);
  });

test('output error event without callback resolves main and destroys output',
  { timeout: 5000 }, async t => {
    await injected(t, '', `
      assert.equal(settled, false);
      output.emit('error', new Error(secret));
      await done;
      assert.equal(output.destroyed, true);
    `);
  });

test('error after successful callback but before main completion cannot restore success',
  { timeout: 5000 }, async t => {
    await injected(t, '', `
      callback();
      assert.equal(settled, false);
      output.emit('error', new Error(secret));
      await done;
      assert.equal(output.destroyed, true);
    `);
  });

test('close after successful callback but before main completion cannot restore success',
  { timeout: 5000 }, async t => {
    await injected(t, '', `
      callback();
      assert.equal(settled, false);
      output.emit('close');
      await done;
      assert.equal(output.destroyed, true);
    `);
  });

test('stalled output hits the actual two-second deadline and destroys the sink',
  { timeout: 6000 }, async t => {
    await injected(t, 'const started = performance.now();', `
      assert.equal(settled, false);
      assert.equal(process.exitCode, 2);
      await delay(100);
      assert.equal(settled, false);
      assert.equal(output.destroyed, false);
      await done;
      assert.ok(performance.now() - started >= 1950);
      assert.equal(writes, 1);
      assert.equal(output.destroyed, true);
      output.emit('error', new Error(secret));
    `);
  });

test('actual subprocess stdout pipe with its reader closed fails with EPIPE silently',
  { timeout: 5000, skip: process.platform === 'win32' }, async t => {
    const child = childProcess(t, `
      import assert from 'node:assert/strict';
      import { setImmediate as turn } from 'node:timers/promises';
      import { main } from ${JSON.stringify(cli.href)};
      const errors = [];
      let destroys = 0;
      const output = process.stdout;
      const emit = output.emit;
      const destroy = output.destroy;
      // Observe the genuine OS error without installing an error listener that
      // could hide an unhandled event. Node's special stdout destroy can be a no-op.
      output.emit = function (event, ...args) {
        if (event === 'error') errors.push(args[0].code);
        return emit.call(this, event, ...args);
      };
      output.destroy = function (...args) {
        destroys++;
        return destroy.apply(this, args);
      };
      process.argv = [process.execPath, ${JSON.stringify(fileURLToPath(cli))}];
      await main();
      await turn();
      assert.deepEqual(errors, ['EPIPE']);
      assert.ok(destroys >= 1);
      assert.equal(process.exitCode, 2);
    `, 'pipe');
    let stderr = '';
    child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
    child.stdin.on('error', () => {});
    const completed = once(child, 'close');
    // Close the sole OS pipe reader before providing EOF/input to main.
    const readerClosed = once(child.stdout, 'close');
    child.stdout.destroy();
    await readerClosed;
    child.stdin.end(JSON.stringify(vector.input));
    const [code, signal] = await completed;
    assert.equal(signal, null);
    assert.equal(stderr, '');
    assert.equal(code, 2);
  });
