import { constants } from 'node:fs';
import { lstat, open } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import SafeReporter from './safe-reporter.mjs';

const CASE_IDS = Object.freeze([
  'RIO-E2E-01', 'RIO-E2E-02', 'RIO-E2E-03', 'RIO-E2E-04', 'RIO-E2E-05',
]);
const CASES = new Set(CASE_IDS);
const STATUSES = new Set(['passed', 'failed', 'timedOut', 'skipped', 'interrupted']);
const MAX_SUITE_ERRORS = 1000;
const RUNTIME = fileURLToPath(new URL('./.tls-runtime', import.meta.url));

function ownValue(source, key) {
  if (!source || typeof source !== 'object' || Array.isArray(source)) return undefined;
  const property = Object.getOwnPropertyDescriptor(source, key);
  return property && Object.hasOwn(property, 'value') ? property.value : undefined;
}

// Only fixed identifiers and status enums cross this boundary. FullResult and
// recorded events may contain credentials or arbitrary exception diagnostics.
export function buildTlsOidcSummary(rows, suiteErrors, fullResult) {
  let errors = Number.isInteger(suiteErrors) && suiteErrors >= 0
    ? Math.min(suiteErrors, MAX_SUITE_ERRORS) : MAX_SUITE_ERRORS;
  const cases = new Map(CASE_IDS.map(id => [id, { id, status: 'failed' }]));
  let valid = false;
  const seen = new Set();
  try {
    valid = Array.isArray(rows) && rows.length === CASE_IDS.length;
    if (Array.isArray(rows)) {
      // A malformed or unexpectedly large suite cannot produce unbounded output.
      for (let index = 0; index < Math.min(rows.length, CASE_IDS.length); index += 1) {
        const id = ownValue(rows[index], 'id');
        const status = ownValue(rows[index], 'status');
        if (!CASES.has(id)) { valid = false; continue; }
        if (seen.has(id)) {
          cases.get(id).status = 'failed';
          valid = false;
          continue;
        }
        seen.add(id);
        if (!STATUSES.has(status)) { valid = false; continue; }
        cases.get(id).status = status;
      }
    }
    valid = valid && seen.size === CASE_IDS.length && errors === 0 &&
      ownValue(fullResult, 'status') === 'passed' &&
      [...cases.values()].every(row => row.status === 'passed');
  } catch {
    // Accessors and proxies must never turn a rejected record into diagnostics.
    valid = false;
    errors = MAX_SUITE_ERRORS;
    for (const row of cases.values()) row.status = 'failed';
  }
  return {
    schema: 'rio-tls-oidc-browser-evidence/v1',
    status: valid ? 'passed' : 'failed',
    suiteErrors: errors,
    tests: [...cases.values()],
  };
}

function sameIdentity(left, right) {
  return left.dev === right.dev && left.ino === right.ino;
}

function privateOwned(metadata, directory = false) {
  return (directory ? metadata.isDirectory() : metadata.isFile()) &&
    metadata.uid === process.getuid() && (metadata.mode & 0o077) === 0 &&
    (directory || metadata.nlink === 1);
}

function requirePrivate(metadata, directory = false) {
  if (!privateOwned(metadata, directory)) throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
}

async function openOwnedFile(directory, name, flags) {
  // /proc pins the already-open directory even if its pathname is renamed.
  const path = `/proc/self/fd/${directory.fd}/${name}`;
  const before = await lstat(path);
  requirePrivate(before);
  const handle = await open(path, flags | constants.O_NOFOLLOW);
  try {
    const after = await handle.stat();
    requirePrivate(after);
    if (!sameIdentity(before, after)) throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
    return handle;
  } catch {
    await handle.close();
    throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
  }
}

async function writeOwnedSummary(summary) {
  // This proof runs on Linux CI. Other platforms make no POSIX ownership claim.
  if (process.platform !== 'linux' || typeof process.getuid !== 'function' ||
      !Number.isInteger(constants.O_NOFOLLOW) || !Number.isInteger(constants.O_DIRECTORY)) {
    throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
  }
  let directory;
  let marker;
  let output;
  try {
    const before = await lstat(RUNTIME);
    requirePrivate(before, true);
    directory = await open(RUNTIME, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    const metadata = await directory.stat();
    requirePrivate(metadata, true);
    if (!sameIdentity(before, metadata)) throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
    marker = await openOwnedFile(directory, '.owner.json', constants.O_RDONLY);
    if ((await marker.stat()).size > 2048) throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
    const markerBuffer = Buffer.alloc(2049);
    const { bytesRead } = await marker.read(markerBuffer, 0, markerBuffer.length, 0);
    if (bytesRead > 2048) throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
    const owner = JSON.parse(markerBuffer.subarray(0, bytesRead).toString('utf8'));
    if (!owner || typeof owner !== 'object' || Array.isArray(owner) ||
        Object.keys(owner).sort().join('|') !== 'ownerToken|project|schemaVersion' ||
        owner.schemaVersion !== 'RIO_TLS_FIXTURE_OWNER_V1' ||
        typeof owner.project !== 'string' || !/^rio-accounts-tls-[0-9a-f]{16}$/.test(owner.project) ||
        typeof owner.ownerToken !== 'string' || !/^[0-9a-f]{64}$/.test(owner.ownerToken)) {
      throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
    }
    output = await openOwnedFile(directory, 'oidc-summary.json', constants.O_WRONLY);
    // The fixture creates and owns this empty file. Never create or replace it.
    if ((await output.stat()).size !== 0) throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
    const current = await lstat(RUNTIME);
    requirePrivate(current, true);
    if (!sameIdentity(metadata, current)) throw new Error('RIO_TLS_OIDC_OUTPUT_REJECTED');
    await output.writeFile(JSON.stringify(summary) + '\n', { encoding: 'utf8' });
    await output.sync();
  } finally {
    await output?.close();
    await marker?.close();
    await directory?.close();
  }
}

export default class TlsOidcReporter extends SafeReporter {
  onTestEnd(test, result) {
    let id = 'UNKNOWN-CASE';
    let status = 'failed';
    try {
      const title = test?.title;
      const match = typeof title === 'string' ? /^\[(RIO-E2E-0[1-5])\]/.exec(title) : null;
      if (match) id = match[1];
      const resultStatus = result?.status;
      if (STATUSES.has(resultStatus)) status = resultStatus;
    } catch {}
    this.results.push({ id, status });
  }

  async onEnd(result) {
    const summary = buildTlsOidcSummary(this.results, this.suiteErrors, result);
    try {
      await writeOwnedSummary(summary);
      process.stdout.write('RIO_TLS_OIDC_BROWSER_SUMMARY ' + JSON.stringify(summary) + '\n');
      return { status: summary.status };
    } catch {
      process.stdout.write('RIO_TLS_OIDC_BROWSER_SUMMARY_WRITE_FAILED\n');
      return { status: 'failed' };
    }
  }
}
