import test from 'node:test';
import assert from 'node:assert/strict';
import {evidencePassed} from './evidence-checks.mjs';

const complete = () => ({
  compile: {status: 0}, run: {status: 0},
  counts: {tests: 20, pass: 20, fail: 0, cancelled: 0, skipped: 0, todo: 0},
  sourceUnchanged: true, commit: {status: 0, stdout: 'a'.repeat(40) + '\n'},
});
test('complete evidence passes', () => assert.equal(evidencePassed(complete()), true));
for (const [name, change] of [
  ['filtered run', x => { x.counts.tests = x.counts.pass = 1; }],
  ['missing summary', x => { x.counts = {}; }],
  ['missing cancellation count', x => { delete x.counts.cancelled; }],
  ['test failure', x => { x.run.status = 1; }],
  ['spawn error despite zero exit', x => { x.run.error = {code: 'EPERM'}; }],
  ['compiler error despite zero exit', x => { x.compile.error = {code: 'EPERM'}; }],
  ['killed child', x => { x.run.signal = 'SIGKILL'; }],
  ['changed sources', x => { x.sourceUnchanged = false; }],
  ['missing commit', x => { x.commit.stdout = ''; }],
  ['commit lookup error', x => { x.commit.error = {code: 'EPERM'}; }],
  ...['fail', 'cancelled', 'skipped', 'todo'].map(k => [k, x => { x.counts[k] = 1; }]),
]) test(name + ' cannot pass', () => {
  const input = complete(); change(input); assert.equal(evidencePassed(input), false);
});
