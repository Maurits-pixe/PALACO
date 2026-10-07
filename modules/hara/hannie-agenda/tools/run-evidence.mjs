import { readFileSync, writeFileSync, readdirSync, lstatSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { join, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir, release } from 'node:os';
import { createHash, randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';

const moduleRoot = fileURLToPath(new URL('../', import.meta.url));
const repoRoot = resolve(moduleRoot, '../../..');
const sha = value => createHash('sha256').update(value).digest('hex');
function walk(path) {
  return readdirSync(path).sort().flatMap(name => {
    const p = join(path, name), s = lstatSync(p);
    if (s.isSymbolicLink()) throw new Error('Symlink in verification source set');
    return s.isDirectory() ? walk(p) : [p];
  });
}
function hashes() {
  const files = [...walk(moduleRoot), join(repoRoot, 'evidence/hara/d012/source-manifest.json'),
    join(repoRoot, 'evidence/hara/d012/README.md'), join(repoRoot, '.github/workflows/hannie-agenda-candidate.yml')].sort();
  return Object.fromEntries(files.map(p => [relative(repoRoot, p), sha(readFileSync(p))]));
}
const runId = randomUUID(), startedAt = new Date().toISOString();
const out = join(repoRoot, 'evidence/hara/d012/runs', runId);
mkdirSync(out, { recursive: true });
const sourceHashes = hashes(), sourceSetSha256 = sha(JSON.stringify(sourceHashes));
const git = args => spawnSync('git', args, { cwd: repoRoot, encoding: 'utf8' });
const commit = git(['rev-parse', 'HEAD']);
const nativeDir = mkdtempSync(join(tmpdir(), 'palaco-d012-native-')), library = join(nativeDir, 'wal-stall.so');
const compileArgs = ['-shared', '-fPIC', '-O2', '-Wall', '-Werror', '-o', library, join(moduleRoot, 'tests/native/wal-stall.c'), '-ldl'];
const compile = spawnSync('gcc', compileArgs, { encoding: 'utf8' });
writeFileSync(join(out, 'compiler.stdout'), compile.stdout || '');
writeFileSync(join(out, 'compiler.stderr'), compile.stderr || '');
const gccVersion = spawnSync('gcc', ['--version'], { encoding: 'utf8' });
let testRun = { status: null, stdout: '', stderr: 'NOT EXECUTED: native compilation failed' };
let nativeSha256 = null;
if (compile.status === 0) {
  nativeSha256 = sha(readFileSync(library));
  testRun = spawnSync(process.execPath, ['--test', '--test-concurrency=1', '--test-reporter=tap', 'tests/calendar.test.mjs', 'tests/frozen-controls.test.mjs'], {
    cwd: moduleRoot, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024,
    env: { ...process.env, D012_NATIVE_LIBRARY: library, D012_TRACE_DIR: out },
  });
}
writeFileSync(join(out, 'tests.tap'), testRun.stdout || '');
writeFileSync(join(out, 'tests.stderr'), testRun.stderr || '');
const count = key => Number(testRun.stdout?.match(new RegExp('^# ' + key + ' (\\d+)$', 'm'))?.[1] || 0);
const counts = Object.fromEntries(['tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'].map(k => [k, count(k)]));
const unchanged = JSON.stringify(hashes()) === JSON.stringify(sourceHashes);
const success = compile.status === 0 && testRun.status === 0 && counts.tests > 0 && counts.tests === counts.pass &&
  !counts.fail && !counts.cancelled && !counts.skipped && !counts.todo && unchanged;
const db = new DatabaseSync(':memory:');
const sqliteVersion = db.prepare('SELECT sqlite_version() AS v').get().v; db.close();
const artifacts = Object.fromEntries(walk(out).map(p => [relative(out, p), sha(readFileSync(p))]));
const result = {
  kind: 'D012_LOCAL_EXECUTION_EVIDENCE', runId, startedAt, endedAt: new Date().toISOString(),
  candidate: '0.3.3-d012.1', repository: 'Maurits-pixe/PALACO', branch: 'hara/hannie-agenda-candidate-v0.3',
  sourceCommitAtStart: commit.status === 0 ? commit.stdout.trim() : 'UNAVAILABLE',
  sourceSetSha256, sourceHashes, hashDefinition: 'SHA-256 of JSON.stringify(sorted repo-relative path to raw-file SHA-256 map); no trailing newline',
  sourceUnchangedAfterRun: unchanged,
  sourceAcquisitionManifestSha256: sha(readFileSync(join(repoRoot, 'evidence/hara/d012/source-manifest.json'))),
  runtime: { node: process.version, sqlite: sqliteVersion, platform: process.platform, architecture: process.arch,
    osRelease: release(), icu: process.versions.icu, nodeBinarySha256: sha(readFileSync(process.execPath)) },
  nativeFixture: { compileExitCode: compile.status, compiler: gccVersion.stdout?.split('\n')[0] || 'UNAVAILABLE',
    flags: ['-shared', '-fPIC', '-O2', '-Wall', '-Werror', '-ldl'], librarySha256: nativeSha256 },
  command: 'node --test --test-concurrency=1 --test-reporter=tap tests/calendar.test.mjs tests/frozen-controls.test.mjs',
  testExitCode: testRun.status, counts, artifacts,
  checks: success ? 'PASS' : compile.status !== 0 ? 'NOT EXECUTED / HARNESS BUILD BLOCKED' : 'FAIL',
  testEvidenceLabel: success ? 'PROVEN_WITHIN_SCOPE' : 'UNVERIFIED',
  scope: 'New isolated local adapter: unconditional mutation denial, tested callback/storage-wait freshness, grant/review/proposal and synthetic historical receipt controls. WAL primitive calibration is not candidate execution.',
  originalHistoricalFixtureBytes: 'UNAVAILABLE; requirement controls newly implemented from primary Notion records',
  successfulCandidateAgendaMutations: 'NOT EXECUTED / BLOCKED',
  absoluteEffectDeadline: 'UNPROVEN; AM-R01 technical capability OPEN',
  revision: 'R1-F01-harness-and-D010-status-2026-10-05',
  temporalDecision: 'D-010 B recorded; durable TACP NOT IMPLEMENTED; acceptance OPEN',
  warningRegressionPreload: process.env.NODE_OPTIONS || null,
  officialPalacoProof: 'NOT ISSUED', independentReview: 'PENDING',
  integration: 'HOLD', production: 'HOLD', deployment: 'NOT DEPLOYED', hostedD1: 'NOT EXECUTED', AM10: 'NOT EXECUTED',
};
writeFileSync(join(out, 'result.json'), JSON.stringify(result, null, 2) + '\n');
rmSync(nativeDir, { recursive: true, force: true });
console.log(JSON.stringify({ runId, result: relative(repoRoot, join(out, 'result.json')), sourceSetSha256, checks: result.checks, counts }));
process.exitCode = success ? 0 : 1;
