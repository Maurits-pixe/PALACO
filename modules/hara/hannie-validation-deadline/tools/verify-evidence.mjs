import {readFileSync, realpathSync, readdirSync, lstatSync} from 'node:fs';
import {resolve, relative, isAbsolute} from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const requireThat = (ok, message) => { if (!ok) throw Error(message); };
function inside(root, name) {
  requireThat(typeof name === 'string' && name.length > 0 && !isAbsolute(name), 'INVALID_PATH');
  const path = realpathSync(resolve(root, name)), rel = relative(root, path);
  requireThat(rel !== '..' && !rel.startsWith('../') && !isAbsolute(rel), 'PATH_ESCAPE');
  return path;
}
function sourceInventory(repo) {
  const module = inside(repo, 'modules/hara/hannie-validation-deadline');
  function walk(dir) {
    return readdirSync(dir).sort().flatMap(name => {
      const path = resolve(dir, name), stat = lstatSync(path);
      requireThat(!stat.isSymbolicLink(), 'SOURCE_SYMLINK');
      return stat.isDirectory() ? walk(path) : [relative(repo, path)];
    });
  }
  return [...walk(module), '.github/workflows/hannie-validation-deadline.yml',
    'evidence/hara/validation-deadline/decision.json'].sort();
}
export function verifyEvidence(directory, repository) {
  const dir = realpathSync(directory), repo = realpathSync(repository);
  const result = JSON.parse(readFileSync(resolve(dir, 'result.json'), 'utf8'));
  requireThat(result.runId === dir.split('/').at(-1), 'RUN_ID_MISMATCH');
  requireThat(result.kind === 'VALIDATION_DEADLINE_EXECUTION_EVIDENCE' && result.checks === 'PASS', 'RUN_NOT_PASS');
  requireThat(result.counts.tests === 23 && result.counts.pass === 23 &&
    ['fail','cancelled','skipped','todo'].every(k => result.counts[k] === 0), 'INCOMPLETE_RUN');
  requireThat(result.sourceUnchangedAfterRun === true && result.compileExit === 0 && result.testExit === 0, 'EXECUTION_MISMATCH');
  requireThat(!result.compileError && !result.testError && !result.compileSignal && !result.testSignal, 'PROCESS_ERROR');
  requireThat(/^[a-f0-9]{40}$/.test(result.sourceCommitAtStart), 'COMMIT_MISSING');
  requireThat(sha(JSON.stringify(result.sourceHashes)) === result.sourceSetSha256, 'SOURCE_SET_MISMATCH');
  requireThat(Object.keys(result.sourceHashes).length > 0, 'SOURCE_HASHES_MISSING');
  for (const [name, hash] of Object.entries(result.sourceHashes))
    requireThat(sha(readFileSync(inside(repo, name))) === hash, 'SOURCE_HASH_MISMATCH: ' + name);
  requireThat(JSON.stringify(Object.keys(result.sourceHashes).sort()) ===
    JSON.stringify(sourceInventory(repo)), 'SOURCE_INVENTORY_MISMATCH');
  const actual = readdirSync(dir).filter(n => n !== 'result.json').sort();
  requireThat(JSON.stringify(actual) === JSON.stringify(Object.keys(result.artifacts).sort()), 'ARTIFACT_SET_MISMATCH');
  requireThat(['tests.tap','tests.stderr',...Array.from({length:23},(_,i)=>'N'+String(i+1).padStart(2,'0')+'.json')].every(n => n in result.artifacts), 'REQUIRED_ARTIFACT_MISSING');
  for (const [name, hash] of Object.entries(result.artifacts))
    requireThat(sha(readFileSync(inside(dir, name))) === hash, 'ARTIFACT_HASH_MISMATCH: ' + name);
  const tap = readFileSync(resolve(dir, 'tests.tap'), 'utf8');
  for (const [name, count] of Object.entries(result.counts)) {
    const matches = [...tap.matchAll(new RegExp('^# ' + name + ' (\\d+)$', 'gm'))];
    requireThat(matches.length === 1 && Number(matches[0][1]) === count, 'TAP_COUNT_MISMATCH: ' + name);
  }
  const late = JSON.parse(readFileSync(resolve(dir, 'N04.json'), 'utf8'));
  requireThat(late.lateEffectExists === true && late.d013Conformance === false && late.newProfile === true &&
    late.r.status === 'COMMITTED' && late.r.receipt?.deadlineSatisfied === 'VALIDATION_DEADLINE_ONLY' &&
    late.r.receipt.validatedAt < late.expiry && late.r.receipt.observedAfterExpiry === true &&
    late.r.receipt.exactDurableAt === 'UNKNOWN' && late.native[0].startMs < late.expiry && late.native[0].endMs > late.expiry,
    'NEW_PROFILE_LATE_COMMIT_EVIDENCE_MISSING');
  requireThat(result.integration === 'HOLD' && result.production === 'HOLD' && result.proof === 'NOT ISSUED', 'AUTHORITY_BOUNDARY_CHANGED');
  return {runId: result.runId, sourceSetSha256: result.sourceSetSha256, sources: Object.keys(result.sourceHashes).length, artifacts: actual.length, verification: 'PASS', acceptance: 'HOLD'};
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    requireThat(process.argv.length === 4, 'USAGE: node verify-evidence.mjs RUN_DIRECTORY REPOSITORY');
    console.log(JSON.stringify(verifyEvidence(process.argv[2], process.argv[3])));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
