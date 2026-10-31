import {readFileSync,readdirSync,lstatSync} from 'node:fs';
import {resolve,relative,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';

const root=fileURLToPath(new URL('../',import.meta.url));
const repo=resolve(root,'../../..');
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const requireEvidence=(condition,code)=>{if(!condition)throw Error(code);};
function files(dir){
 return readdirSync(dir).sort().flatMap(name=>{
  const path=join(dir,name),stat=lstatSync(path);
  requireEvidence(!stat.isSymbolicLink(),'EVIDENCE_SYMLINK');
  return stat.isDirectory()?files(path):[path];
 });
}
function contained(base,name){
 requireEvidence(typeof name==='string' && name.length>0,'INVALID_PATH');
 const path=resolve(base,name),rel=relative(base,path);
 requireEvidence(rel!=='' && !rel.startsWith('..') && !rel.startsWith('/'),'PATH_ESCAPE');
 // Reject symlink components as well as a symlink at the final file.
 let current=base;
 for(const part of rel.split('/')){
  current=join(current,part);
  requireEvidence(!lstatSync(current).isSymbolicLink(),'EVIDENCE_SYMLINK');
 }
 return path;
}
try {
 requireEvidence(process.argv.length===3,'SUMMARY_REQUIRED');
 const summary=JSON.parse(readFileSync(process.argv[2],'utf8'));
 requireEvidence(/^[0-9a-f]{8}-[0-9a-f-]{27}$/.test(summary.runId),'INVALID_RUN_ID');
 const dir=join(repo,'evidence/hara/b-d013/runs',summary.runId);
 requireEvidence(!lstatSync(dir).isSymbolicLink(),'EVIDENCE_SYMLINK');
 const result=JSON.parse(readFileSync(contained(dir,'result.json'),'utf8'));
 requireEvidence(result.kind==='B_D013_EXECUTION_EVIDENCE' && result.runId===summary.runId,'RUN_BINDING');
 requireEvidence(result.checks==='PASS' && summary.checks==='PASS','RUN_NOT_PASS');
 requireEvidence(result.sourceUnchangedAfterRun===true,'SOURCE_CHANGED');
 requireEvidence(result.compileExit===0 && !result.compileSignal && !result.compileSpawnError && result.testExit===0 && !result.testSignal && !result.testSpawnError,'PROCESS_FAILURE');
 requireEvidence(['none','process'].includes(result.testIsolation),'INVALID_ISOLATION');
 const expected={tests:22,pass:22,fail:0,cancelled:0,skipped:0,todo:0};
 for(const [key,value] of Object.entries(expected)){
  requireEvidence(result.counts?.[key]===value && summary.counts?.[key]===value,'COUNT_MISMATCH');
 }
 requireEvidence(result.expectedTests===22,'EXPECTED_COUNT_MISMATCH');
 const sourcePaths=[...files(root),join(repo,'.github/workflows/hannie-b-d013.yml'),join(repo,'evidence/hara/b-d013/source-manifest.json')].sort();
 const sources=Object.fromEntries(sourcePaths.map(path=>[relative(repo,path),sha(readFileSync(path))]));
 requireEvidence(JSON.stringify(sources)===JSON.stringify(result.sourceHashes),'SOURCE_HASH_MISMATCH');
 const sourceSet=sha(JSON.stringify(sources));
 requireEvidence(sourceSet===result.sourceSetSha256 && sourceSet===summary.sourceSetSha256,'SOURCE_SET_MISMATCH');
 const artifactNames=files(dir).map(path=>relative(dir,path)).filter(name=>name!=='result.json').sort();
 const required=['compiler.stderr','tests.stderr','tests.tap',
  ...['B01','B02','B03','B04','B05','B06','B10','B11','B12','B13','B14','BR01','BR02','BR03','BR04','BR05','BR06-action','BR06-calendar_id'].map(name=>name+'.json')];
 requireEvidence(required.every(name=>artifactNames.includes(name)),'REQUIRED_ARTIFACT_MISSING');
 requireEvidence(JSON.stringify(artifactNames)===JSON.stringify(Object.keys(result.artifacts).sort()),'ARTIFACT_SET_MISMATCH');
 for(const name of artifactNames){
  requireEvidence(sha(readFileSync(contained(dir,name)))===result.artifacts[name],'ARTIFACT_HASH_MISMATCH');
 }
 const tap=readFileSync(contained(dir,'tests.tap'),'utf8');
 for(const [key,value] of Object.entries(expected)){
  const matches=[...tap.matchAll(new RegExp('^# '+key+' (\\d+)$','gm'))];
  requireEvidence(matches.length===1 && Number(matches[0][1])===value,'TAP_COUNT_MISMATCH');
 }
 requireEvidence(readFileSync(contained(dir,'compiler.stderr'),'utf8')==='' && readFileSync(contained(dir,'tests.stderr'),'utf8')==='','UNEXPECTED_STDERR');
 console.log(JSON.stringify({runId:result.runId,sourceSetSha256:sourceSet,artifacts:artifactNames.length,verification:'PASS',scope:'Local source and evidence consistency; no independent authority or acceptance'}));
} catch(error){
 console.error(JSON.stringify({verification:'FAIL',code:error.message}));
 process.exitCode=1;
}
