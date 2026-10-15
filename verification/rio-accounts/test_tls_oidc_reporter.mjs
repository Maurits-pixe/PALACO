import assert from 'node:assert/strict';
import { chmod, copyFile, link, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import TlsOidcReporter, { buildTlsOidcSummary } from './tls-oidc-reporter.mjs';

const CANARY = 'PRIVATE-CANARY-token-cookie-password=https://secret.invalid/?code=secret';
const passed = () => Array.from({ length: 5 }, (_, index) => ({
  id: `RIO-E2E-0${index + 1}`, status: 'passed',
}));
const build = (rows = passed(), suiteErrors = 0, fullResult = { status: 'passed' }) =>
  buildTlsOidcSummary(rows, suiteErrors, fullResult);

test('requires exactly the existing five successful real OIDC cases', () => {
  const result = build();
  assert.deepEqual(Object.keys(result), ['schema', 'status', 'suiteErrors', 'tests']);
  assert.equal(result.schema, 'rio-tls-oidc-browser-evidence/v1');
  assert.equal(result.status, 'passed');
  assert.equal(result.suiteErrors, 0);
  assert.deepEqual(result.tests, passed());
});

test('zero, missing, duplicate, unknown and extra cases cannot claim success', () => {
  for (const rows of [
    [], passed().slice(1), [...passed().slice(0, 4), passed()[0]],
    [...passed().slice(0, 4), { id: CANARY, status: 'passed' }],
    [...passed(), { id: CANARY, status: 'passed' }], null, {},
  ]) {
    const result = build(rows);
    assert.equal(result.status, 'failed');
    assert.equal(result.tests.length, 5);
    assert.deepEqual(result.tests.map(row => row.id), passed().map(row => row.id));
    assert.equal(JSON.stringify(result).includes(CANARY), false);
  }
  const duplicate = build([...passed().slice(0, 4), passed()[0]]);
  assert.equal(duplicate.tests[0].status, 'failed');
  assert.equal(duplicate.tests[4].status, 'failed');
});

test('skips, interruptions, timeouts, failures and fabricated statuses fail closed', () => {
  for (const status of ['skipped', 'interrupted', 'timedOut', 'failed', 'PASS', CANARY, null, {}]) {
    const rows = passed();
    rows[2].status = status;
    const summary = build(rows);
    assert.equal(summary.status, 'failed');
    assert.equal(JSON.stringify(summary).includes(CANARY), false);
  }
});

test('FullResult success and no suite error are independently required', () => {
  for (const status of ['failed', 'timedout', 'interrupted', 'PASS', CANARY, undefined]) {
    assert.equal(build(passed(), 0, { status }).status, 'failed');
  }
  for (const errors of [1, 1000, 1001, Number.MAX_SAFE_INTEGER, -1, 1.5, NaN, Infinity, CANARY, null, {}]) {
    const result = build(passed(), errors);
    assert.equal(result.status, 'failed');
    assert.equal(Number.isInteger(result.suiteErrors), true);
    assert.ok(result.suiteErrors >= 0 && result.suiteErrors <= 1000);
    assert.equal(JSON.stringify(result).includes(CANARY), false);
  }
  assert.equal(build(passed(), 1001).suiteErrors, 1000);
});

test('poisoned raw fields, titles, errors, cookies, annotations and tokens never escape', () => {
  const rows = passed().map(row => ({
    ...row, title: CANARY, error: new Error(CANARY), url: CANARY,
    annotations: [{ type: CANARY, description: CANARY }],
    cookies: [CANARY], access_token: CANARY, toJSON() { throw new Error(CANARY); },
  }));
  const fullResult = { status: 'passed', error: CANARY, access_token: CANARY };
  assert.equal(build(rows, 0, fullResult).status, 'passed');
  assert.equal(JSON.stringify(build(rows, 0, fullResult)).includes(CANARY), false);
  const getter = { status: 'passed', get id() { throw new Error(CANARY); } };
  assert.equal(build([getter, ...passed().slice(1)]).status, 'failed');
  const proxy = new Proxy({}, { getOwnPropertyDescriptor() { throw new Error(CANARY); } });
  const rejected = build([proxy, ...passed().slice(1)]);
  assert.equal(rejected.status, 'failed');
  assert.equal(JSON.stringify(rejected).includes(CANARY), false);
  const revoked = Proxy.revocable([], {});
  revoked.revoke();
  assert.equal(build(revoked.proxy).status, 'failed');
  const poisonedLength = new Proxy([], { get() { throw new Error(CANARY); } });
  assert.equal(build(poisonedLength).status, 'failed');
});

test('input, output and repeated summaries share no mutable row or array aliases', () => {
  const rows = passed();
  const first = build(rows);
  rows[0].status = 'failed';
  assert.equal(first.tests[0].status, 'passed');
  first.tests[1].status = CANARY;
  first.tests.push({ id: CANARY });
  assert.deepEqual(build().tests, passed());
  assert.equal(rows.length, 5);
  assert.equal(rows[1].status, 'passed');
});

test('reporter ignores raw output and records only fixed case/status fields', () => {
  const reporter = new TlsOidcReporter();
  assert.equal(reporter.printsToStdio(), true);
  assert.equal(reporter.onStdOut(CANARY), undefined);
  assert.equal(reporter.onStdErr(CANARY), undefined);
  for (const row of passed()) reporter.onTestEnd(
    { title: `[${row.id}] ${CANARY}`, annotations: [CANARY] },
    { status: row.status, error: new Error(CANARY), stdout: [CANARY] },
  );
  assert.deepEqual(reporter.results, passed());
  reporter.onError(new Error(CANARY));
  assert.equal(buildTlsOidcSummary(reporter.results, reporter.suiteErrors, { status: 'passed' }).status, 'failed');
  const invalid = new TlsOidcReporter();
  invalid.onTestEnd({ title: CANARY }, { status: CANARY });
  assert.deepEqual(invalid.results, [{ id: 'UNKNOWN-CASE', status: 'failed' }]);
});

const linux = { skip: process.platform !== 'linux' };

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'rio-tls-oidc-reporter-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const name of ['tls-oidc-reporter.mjs', 'safe-reporter.mjs', 'login-observation.mjs', 'post-consent-observation.mjs']) {
    await copyFile(new URL(name, import.meta.url), join(root, name));
  }
  const runtime = join(root, '.tls-runtime');
  await mkdir(runtime, { mode: 0o700 });
  await writeFile(join(runtime, '.owner.json'), JSON.stringify({
    schemaVersion: 'RIO_TLS_FIXTURE_OWNER_V1',
    project: 'rio-accounts-tls-' + 'a'.repeat(16), ownerToken: 'b'.repeat(64),
  }), { mode: 0o600 });
  const output = join(runtime, 'oidc-summary.json');
  await writeFile(output, '', { mode: 0o600 });
  return { root, runtime, output, marker: join(runtime, '.owner.json') };
}

function runReporter(root) {
  return spawnSync(process.execPath, ['--input-type=module', '-e', `
    import Reporter from './tls-oidc-reporter.mjs';
    const reporter = new Reporter();
    reporter.results = Array.from({ length: 5 }, (_, index) => ({ id: 'RIO-E2E-0' + (index + 1), status: 'passed' }));
    const result = await reporter.onEnd({ status: 'passed' });
    process.exitCode = result.status === 'passed' ? 0 : 1;
  `], { cwd: root, encoding: 'utf8', timeout: 10_000 });
}

function assertRejected(result) {
  assert.equal(result.status, 1);
  assert.equal(result.stdout, 'RIO_TLS_OIDC_BROWSER_SUMMARY_WRITE_FAILED\n');
  assert.equal(result.stderr, '');
  assert.equal(result.stdout.includes(CANARY), false);
}

test('writes only the existing private owned empty summary file', linux, async t => {
  const { root, output } = await fixture(t);
  const result = runReporter(root);
  assert.equal(result.status, 0);
  assert.equal(result.stderr, '');
  assert.deepEqual(JSON.parse(await readFile(output, 'utf8')), build());
  assert.equal(result.stdout, 'RIO_TLS_OIDC_BROWSER_SUMMARY ' + JSON.stringify(build()) + '\n');
  assertRejected(runReporter(root));
});

test('unsupported platforms refuse output without a global fallback', { skip: process.platform === 'linux' }, async t => {
  const { root, output } = await fixture(t);
  assertRejected(runReporter(root));
  assert.equal(await readFile(output, 'utf8'), '');
});

test('rejects missing runtime, missing output, unsafe modes and invalid owner marker', linux, async t => {
  for (const kind of ['runtime-missing', 'output-missing', 'runtime-public', 'output-public', 'marker-public', 'marker-invalid']) {
    const { root, runtime, output, marker } = await fixture(t);
    if (kind === 'runtime-missing') await rm(runtime, { recursive: true });
    if (kind === 'output-missing') await rm(output);
    if (kind === 'runtime-public') await chmod(runtime, 0o755);
    if (kind === 'output-public') await chmod(output, 0o644);
    if (kind === 'marker-public') await chmod(marker, 0o644);
    if (kind === 'marker-invalid') await writeFile(marker, JSON.stringify({ schemaVersion: CANARY }));
    assertRejected(runReporter(root));
    if (kind === 'runtime-missing' || kind === 'output-missing') {
      await assert.rejects(readFile(output), { code: 'ENOENT' });
    } else assert.equal(await readFile(output, 'utf8'), '');
  }
});

test('rejects output symlinks, hard links, directories and nonempty files without touching targets', linux, async t => {
  for (const kind of ['symlink', 'hardlink', 'directory', 'nonempty']) {
    const { root, output } = await fixture(t);
    const target = join(root, 'must-remain-private');
    const original = ['symlink', 'hardlink'].includes(kind) ? '' : CANARY;
    await writeFile(target, original, { mode: 0o600 });
    if (kind === 'nonempty') await writeFile(output, CANARY);
    else {
      await rm(output);
      if (kind === 'symlink') await symlink(target, output);
      if (kind === 'hardlink') await link(target, output);
      if (kind === 'directory') await mkdir(output, { mode: 0o700 });
    }
    assertRejected(runReporter(root));
    assert.equal(await readFile(target, 'utf8'), original);
    if (kind === 'nonempty') assert.equal(await readFile(output, 'utf8'), CANARY);
  }
});

test('rejects a symlinked runtime or owner marker without touching their targets', linux, async t => {
  for (const kind of ['runtime', 'marker']) {
    const { root, runtime, marker, output } = await fixture(t);
    if (kind === 'runtime') {
      const moved = join(root, 'private-runtime');
      await mkdir(moved, { mode: 0o700 });
      await copyFile(marker, join(moved, '.owner.json'));
      await writeFile(join(moved, 'oidc-summary.json'), '', { mode: 0o600 });
      await rm(runtime, { recursive: true });
      await symlink(moved, runtime);
      assertRejected(runReporter(root));
      assert.equal(await readFile(join(moved, 'oidc-summary.json'), 'utf8'), '');
    } else {
      const target = join(root, 'private-owner');
      await copyFile(marker, target);
      await rm(marker);
      await symlink(target, marker);
      assertRejected(runReporter(root));
      assert.equal(await readFile(output, 'utf8'), '');
    }
  }
});
