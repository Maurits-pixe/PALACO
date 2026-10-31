import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, writeFileSync, rmSync, symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {verifyEvidence} from './verify-evidence.mjs';
const sha = x => createHash('sha256').update(x).digest('hex');
function fixture(t) {
  const repo = mkdtempSync(join(tmpdir(), 'hara-verifier-')), dir = join(repo, 'run-1');
  mkdirSync(dir); t.after(() => rmSync(repo, {recursive: true, force: true}));
  writeFileSync(join(repo, 'source'), 'source bytes');
  const counts = {tests:20, pass:20, fail:0, cancelled:0, skipped:0, todo:0};
  const files = {'tests.tap':Object.entries(counts).map(([k,v]) => '# '+k+' '+v).join('\n')+'\n', 'tests.stderr':'', 'B12.json':JSON.stringify({lateEffectExists:true,acceptedTimelySuccess:false,r:{status:'COMMITTED_RESULT_WITHHELD'}})};
  for (const [name, bytes] of Object.entries(files)) writeFileSync(join(dir,name), bytes);
  const sourceHashes = {source:sha('source bytes')};
  const result = {kind:'B_D013_EXECUTION_EVIDENCE',runId:'run-1',checks:'PASS',counts,sourceUnchangedAfterRun:true,compileExit:0,testExit:0,sourceCommitAtStart:'a'.repeat(40),sourceHashes,sourceSetSha256:sha(JSON.stringify(sourceHashes)),artifacts:Object.fromEntries(Object.entries(files).map(([p,b])=>[p,sha(b)])),integration:'HOLD',production:'HOLD',proof:'NOT ISSUED'};
  const save = () => writeFileSync(join(dir,'result.json'), JSON.stringify(result)); save();
  return {repo,dir,result,save};
}
test('valid bound run verifies while acceptance stays HOLD', t => {
  const f=fixture(t); assert.equal(verifyEvidence(f.dir,f.repo).acceptance,'HOLD');
});
for (const [name, change, expected] of [
  ['tampered artifact', f=>writeFileSync(join(f.dir,'tests.tap'),'tampered'), /ARTIFACT_HASH_MISMATCH/],
  ['tampered source', f=>writeFileSync(join(f.repo,'source'),'tampered'), /SOURCE_HASH_MISMATCH/],
  ['wrong run', f=>{f.result.runId='other';}, /RUN_ID_MISMATCH/],
  ['unlisted artifact', f=>writeFileSync(join(f.dir,'extra'),'extra'), /ARTIFACT_SET_MISMATCH/],
  ['partial run', f=>{f.result.counts.tests=1;}, /INCOMPLETE_RUN/],
  ['forged counters', f=>{f.result.counts.tests=20;f.result.counts.pass=20;const bytes='# tests 1\n# pass 1\n';writeFileSync(join(f.dir,'tests.tap'),bytes);f.result.artifacts['tests.tap']=sha(bytes);}, /TAP_COUNT_MISMATCH/],
  ['removed counterevidence', f=>{const bytes='{}';writeFileSync(join(f.dir,'B12.json'),bytes);f.result.artifacts['B12.json']=sha(bytes);}, /LATE_EFFECT_COUNTEREVIDENCE_MISSING/],
  ['authority promotion', f=>{f.result.production='GO';}, /AUTHORITY_BOUNDARY_CHANGED/],
  ['source path escape', f=>{f.result.sourceHashes={'../outside':'x'};f.result.sourceSetSha256=sha(JSON.stringify(f.result.sourceHashes));}, /ENOENT|PATH_ESCAPE/],
  ['source symlink escape', f=>{symlinkSync('/etc/hostname',join(f.repo,'escape'));f.result.sourceHashes={escape:'x'};f.result.sourceSetSha256=sha(JSON.stringify(f.result.sourceHashes));}, /PATH_ESCAPE/],
]) test(name+' is rejected', t=>{
  const f=fixture(t);change(f);f.save();assert.throws(()=>verifyEvidence(f.dir,f.repo),expected);
});
