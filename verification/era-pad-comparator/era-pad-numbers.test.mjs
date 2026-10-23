import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { compareEraPadJson } from './era-pad-json.mjs';

const corpus = JSON.parse(readFileSync(new URL('./era-pad-vectors.v0.1.json', import.meta.url), 'utf8'));
const golden = corpus.vectors.find(vector => vector.id === 'synthetic-pass-known-time');
const invalid = corpus.vectors.find(vector => vector.id === 'synthetic-extra-authority-sanitized').expected_status;
const cli = fileURLToPath(new URL('./era-pad-cli.mjs', import.meta.url));
const fractionalUnderflow = `0.${'0'.repeat(400)}1`;
const rejected = [
  '1e-999', '1.234e-999', '0.0000001e-999', '2e-324', fractionalUnderflow,
  '-1e-999', '-1.234e-999', '-0.0000001e-999', '-2e-324', `-${fractionalUnderflow}`,
  '1e999', '-1e999', '-0', '-0e-999', '-0.000e+999',
];
const exactZeros = ['0', '0e-999', '0.000e+999', '0E+999', '0.000E-999'];
const tinyPositives = ['5e-324', '1e-300'];

function bytes(token, unit) {
  const input = structuredClone(golden.input);
  input.temporal.uncertainty.unit = unit;
  const json = JSON.stringify(input);
  assert.equal(json.split('"value":0').length, 2);
  return Buffer.from(json.replace('"value":0', `"value":${token}`));
}

function expected(temporalStatus) {
  return temporalStatus === null ? invalid : { ...golden.expected_status, temporal_status: temporalStatus };
}

for (const unit of ['s', 'ms']) {
  test(`JSON numeric underflow, overflow and negative zero are sanitized (${unit})`, () => {
    for (const token of rejected) {
      assert.deepEqual(compareEraPadJson(bytes(token, unit)), invalid, token);
    }
  });

  test(`JSON exact zero and representable tiny positives retain distinct statuses (${unit})`, () => {
    for (const [tokens, temporalStatus] of [[exactZeros, 'KNOWN'], [tinyPositives, 'UNKNOWN']]) {
      for (const token of tokens) {
        const { pad, temporal, ...status } = compareEraPadJson(bytes(token, unit));
        assert.deepEqual(status, expected(temporalStatus), token);
        assert.deepEqual(pad, golden.input.pad);
        assert.deepEqual(temporal, {
          ...golden.input.temporal,
          uncertainty: { value: JSON.parse(token), unit },
        });
        assert.equal(temporal.uncertainty.value === 0, temporalStatus === 'KNOWN', token);
      }
    }
  });

  for (const [token, temporalStatus] of [
    ['1e-999', null], ['1.234e-999', null], ['0.0000001e-999', null],
    ['2e-324', null], [fractionalUnderflow, null], ['-1e-999', null],
    ['1e999', null], ['-0', null], ['-0e-999', null],
    ['0e-999', 'KNOWN'], ['0.000e+999', 'KNOWN'],
    ['5e-324', 'UNKNOWN'], ['1e-300', 'UNKNOWN'],
  ]) {
    const label = token === fractionalUnderflow ? 'long fractional underflow' : token;
    test(`fresh CLI numeric token ${label} (${unit})`, { timeout: 5000 }, async t => {
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
      child.stdin.end(bytes(token, unit));
      const [code, signal] = await completed;
      assert.equal(signal, null);
      assert.equal(code, temporalStatus === null ? 2 : golden.expected_cli_exit);
      assert.equal(stderr, '');
      assert.equal(stdout, `${JSON.stringify(expected(temporalStatus))}\n`);
    });
  }
}
