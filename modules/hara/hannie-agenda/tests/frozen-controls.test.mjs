import test from 'node:test';
import assert from 'node:assert/strict';
import { fork, spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { fixture, createInput, prepared, seedCommitted, databaseState, waitUntil, regrant } from './helpers.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const frozen = JSON.parse(readFileSync(join(here, 'frozen-controls.json'), 'utf8'));
// R1-F01: suppress only the known experimental runtime diagnostic in WAL children.
// Keep the strict stderr assertion so other warnings/errors remain failures.
const walExecArgv = [...process.execArgv, '--disable-warning=ExperimentalWarning'];
const denies = (fn, code) => assert.throws(fn, e => e.code === code);
function use(t, opts = {}) { const f = fixture(opts); t.after(() => f.close()); return f; }
function trace(name, value) {
  if (process.env.D012_TRACE_DIR) writeFileSync(join(process.env.D012_TRACE_DIR, name + '.json'), JSON.stringify(value, null, 2) + '\n');
}
function message(child, kind) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error('Child timeout waiting for ' + kind)); }, 12000);
    const onMessage = m => { if (m.kind === kind) { cleanup(); resolve(m); } };
    const onExit = code => { cleanup(); reject(new Error('Child exited before ' + kind + ': ' + code)); };
    function cleanup() { clearTimeout(timer); child.off('message', onMessage); child.off('exit', onExit); child.off('error', onExit); }
    child.on('message', onMessage); child.once('exit', onExit); child.once('error', onExit);
  });
}
async function walScenario(t, route, deadlineKind) {
  const dir = mkdtempSync(join(tmpdir(), 'palaco-d012-wal-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  let library = process.env.D012_NATIVE_LIBRARY;
  if (!library) {
    library = join(dir, 'wal-stall.so');
    const c = spawnSync('gcc', ['-shared', '-fPIC', '-O2', '-Wall', '-Werror', '-o', library, join(here, 'native/wal-stall.c'), '-ldl'], { encoding: 'utf8' });
    assert.equal(c.status, 0, c.stderr);
  }
  const writer = fork(join(here, 'wal-worker.mjs'), [dir, route, deadlineKind], {
    execArgv: walExecArgv,
    env: { ...process.env, LD_PRELOAD: library, D012_WAL_PATH: join(dir, 'calendar.sqlite-wal'), D012_WAL_ARM: join(dir, 'arm'), D012_WAL_TRACE: join(dir, 'native.jsonl') },
    stdio: ['ignore', 'pipe', 'pipe', 'ipc'] });
  let stderr = ''; writer.stderr.on('data', x => { stderr += x; });
  t.after(() => { if (!writer.killed && writer.exitCode === null) writer.kill(); });
  const ready = await message(writer, 'READY');
  assert.ok(ready.deadline > Date.now(), 'Valid future deadline before hazard');
  const reader = fork(join(here, 'wal-reader.mjs'), [dir, String(ready.deadline), route], { stdio: ['ignore', 'pipe', 'pipe', 'ipc'] });
  t.after(() => { if (!reader.killed && reader.exitCode === null) reader.kill(); });
  await message(reader, 'READY');
  const wd = message(writer, 'DONE'), rd = message(reader, 'DONE');
  reader.send({ kind: 'GO' }); writer.send({ kind: 'GO' });
  const [w, r] = await Promise.all([wd, rd]);
  assert.equal(stderr, '');
  const native = existsSync(join(dir, 'native.jsonl')) ? readFileSync(join(dir, 'native.jsonl'), 'utf8').trim().split('\n').map(x => JSON.parse(x)) : [];
  const result = { writer: w, reader: r, native };
  trace(route + '-' + deadlineKind, result);
  return result;
}
test('R1-F01 selective warning suppression retains unexpected diagnostics and errors', () => {
  const launch = source => spawnSync(process.execPath, [...walExecArgv, '--input-type=module', '-e', source], {
    encoding: 'utf8', env: { ...process.env, NODE_OPTIONS: '' },
  });
  const experimental = launch("process.emitWarning('SQLite regression warning', { type: 'ExperimentalWarning' });");
  assert.equal(experimental.status, 0); assert.equal(experimental.stderr, '');
  const unexpected = launch("process.emitWarning('unexpected diagnostic', { type: 'D012UnexpectedWarning' });");
  assert.equal(unexpected.status, 0); assert.match(unexpected.stderr, /D012UnexpectedWarning: unexpected diagnostic/);
  const error = launch("throw new Error('unexpected child failure');");
  assert.notEqual(error.status, 0); assert.match(error.stderr, /unexpected child failure/);
});
test('HARNESS-CALIBRATION real 2400ms WAL stall and second-process late effect (privileged primitive, not candidate execution)', async t => {
  const { writer: w, reader: r, native } = await walScenario(t, 'primitive-calibration', 'grant-and-approval');
  assert.equal(native.length, 1); assert.equal(native[0].pathConfirmed, true);
  assert.equal(native[0].delayMs, frozen.storage.delayMs);
  assert.ok(native[0].startMs < w.deadline && native[0].endMs > w.deadline);
  assert.ok(r.zeroAfterExpiry); assert.ok(r.firstEffectAt > w.deadline);
  assert.equal(w.eventCount, 1); assert.equal(w.injectorReached, true);
});
for (const kind of ['grant-and-approval', 'approval-only']) {
  test('FROZEN-TIME-' + kind + ' exact approved candidate request cannot enter armed WAL hazard', async t => {
    const { writer: w, reader: r, native } = await walScenario(t, 'candidate-deny', kind);
    assert.equal(w.code, 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED'); assert.equal(w.unchanged, true);
    assert.equal(w.noAuthorityCalls, true); assert.equal(w.eventCount, 0);
    assert.equal(w.injectorReached, false); assert.equal(native.length, 0);
    assert.equal(r.effects, 0); assert.equal(r.firstEffectAt, null); assert.ok(r.zeroAfterExpiry);
  });
}
for (const [label, method, dependency] of [
  ['READ-I01-CONTEXT', 'readEvent', 'context'], ['RECOVER-I01-CONTEXT', 'recover', 'context'], ['READ-I02-POLICY', 'readEvent', 'policy'],
  ['RECOVER-POLICY', 'recover', 'policy'], ['READ-STORAGE', 'readEvent', 'storage'], ['RECOVER-STORAGE', 'recover', 'storage'],
  ['PREPARE-CONTEXT', 'prepare', 'context'], ['PREPARE-POLICY', 'prepare', 'policy'], ['PREPARE-STORAGE', 'prepare', 'storage'],
  ['REVISE-CONTEXT', 'revise', 'context'], ['REVISE-POLICY', 'revise', 'policy'], ['REVISE-STORAGE', 'revise', 'storage'],
]) {
  test('FROZEN-FRESHNESS-' + label + ' no content at expiry + 150ms', t => {
    const f = use(t, { realClock: true, expiresMs: 250 }), h = seedCommitted(f);
    const previous = method === 'revise' ? prepared(f) : null;
    const before = databaseState(f.db);
    let waited = false;
    const pause = () => { if (!waited) { waited = true; waitUntil(f.grant.expiresAt + frozen.read.waitEndsAfterExpiryMs); } };
    if (dependency === 'context') f.state.contextHook = pause;
    else if (dependency === 'policy') f.state.policyHook = pause;
    else f.state.releaseHook = pause;
    let code;
    if (method === 'recover') {
      const r = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
      assert.equal(r.status, 'RESULT_UNKNOWN'); assert.equal(r.event, undefined); assert.equal(r.receiptId, undefined); code = r.code;
    } else if (method === 'readEvent') {
      denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), 'CONSENT_INACTIVE'); code = 'CONSENT_INACTIVE';
    } else if (method === 'prepare') {
      denies(() => f.adapter.prepare('OWNER', createInput()), 'CONSENT_INACTIVE'); code = 'CONSENT_INACTIVE';
    } else {
      denies(() => f.adapter.revise('OWNER', { proposalId: previous.proposal.proposalId, digest: previous.proposal.digest, replacement: createInput() }), 'CONSENT_INACTIVE'); code = 'CONSENT_INACTIVE';
    }
    assert.ok(waited); assert.ok(Date.now() - f.grant.expiresAt >= 150);
    if (['readEvent', 'recover'].includes(method)) assert.equal(databaseState(f.db), before);
    assert.equal(f.db.prepare('SELECT COUNT(*) n FROM events').get().n, 1);
    trace(label, { code, dependency, method, observedAfterExpiryMs: Date.now() - f.grant.expiresAt, eventCount: 1, contentReleased: false });
  });
}
test('FRESHNESS-ACTUAL-WRITER-LOCK grant re-evaluated after SQLite contention', async t => {
  const f = use(t, { realClock: true, expiresMs: 400 }), h = seedCommitted(f);
  const child = fork(join(here, 'lock-worker.mjs'), [f.path, String(f.grant.expiresAt + 150)], { stdio: ['ignore', 'pipe', 'pipe', 'ipc'] });
  t.after(() => { if (child.exitCode === null) child.kill(); });
  await message(child, 'READY');
  const done = message(child, 'DONE'), before = databaseState(f.db);
  denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), 'CONSENT_INACTIVE');
  await done; assert.equal(databaseState(f.db), before);
  trace('ACTUAL-WRITER-LOCK', { observedAfterExpiryMs: Date.now() - f.grant.expiresAt, contentReleased: false });
});
test('FRESHNESS-POSITIVE explicit HANNIE title and receipt permissions before expiry survive release waits', t => {
  const f = use(t, { realClock: true, expiresMs: 5000 }), h = seedCommitted(f);
  f.state.releaseHook = () => waitUntil(Date.now() + 10);
  assert.equal(f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }).event.title, 'Synthetic title');
  assert.equal(f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest }).status, 'SUCCEEDED');
});
test('FRESHNESS-REGRANT new generation during storage callback does not revive the old request', t => {
  const f = use(t), h = seedCommitted(f); let once = true;
  f.state.releaseHook = () => { if (once) { once = false; regrant(f); } };
  denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), 'CONSENT_GENERATION_CHANGED');
});
for (const dependency of ['context', 'policy']) {
  test('FRESHNESS-ACTUAL-WRITER-LOCK-' + dependency + ' loss of authority during contention denies content', async t => {
    const f = use(t, { realClock: true, expiresMs: 60000 }), h = seedCommitted(f);
    let changeAt = Infinity;
    const original = f.state.context;
    if (dependency === 'context') f.state.context = actor => ({ ...original(actor), admitted: Date.now() < changeAt });
    else f.state.policyHook = () => { if (Date.now() >= changeAt) f.state.policy = { ...f.state.policy, enabled: false }; };
    const child = fork(join(here, 'lock-worker.mjs'), [f.path, 'IPC'], { stdio: ['ignore', 'pipe', 'pipe', 'ipc'] });
    t.after(() => { if (child.exitCode === null) child.kill(); });
    await message(child, 'READY'); const done = message(child, 'DONE'), before = databaseState(f.db);
    changeAt = Date.now() + 100; child.send({ holdUntil: changeAt + 150 });
    denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), dependency === 'context' ? 'AUTH_CONTEXT_DENIED' : 'POLICY_BLOCKED');
    await done; assert.equal(databaseState(f.db), before);
    trace('ACTUAL-WRITER-LOCK-' + dependency, { contentReleased: false, authorityChangedDuringWait: true });
  });
}
test('FRESHNESS-OWNER-METADATA expiry during final callback preserves only the narrow historical exception', t => {
  const f = use(t, { realClock: true, expiresMs: 200 }), h = seedCommitted(f);
  f.state.releaseHook = () => waitUntil(f.grant.expiresAt + 150);
  const r = f.adapter.recover('OWNER', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
  assert.equal(r.status, 'COMMITTED_RESULT_WITHHELD'); assert.equal(r.event, undefined); assert.equal(r.eventId, undefined);
});
