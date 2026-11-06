import {readFileSync,writeFileSync,readdirSync,lstatSync,mkdirSync,mkdtempSync,rmSync,appendFileSync,openSync,closeSync} from 'node:fs';
import {join,resolve,relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir,release} from 'node:os';
import {randomUUID,createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {verifyEvidence} from './verify-evidence.mjs';

const runChild=async(command,args,options={})=>{
 const dir=mkdtempSync(join(tmpdir(),'hara-process-')),stdoutPath=join(dir,'stdout'),stderrPath=join(dir,'stderr');
 const outFd=openSync(stdoutPath,'w'),errFd=openSync(stderrPath,'w');
 try {return await new Promise(resolve=>{
  const child=spawn(command,args,{...options,stdio:['ignore',outFd,errFd]});let error=null;
  child.on('error',e=>{error={code:e.code,message:e.message};});
  child.on('close',(status,signal)=>resolve({status,signal,error,stdout:readFileSync(stdoutPath,'utf8'),stderr:readFileSync(stderrPath,'utf8')}));
 });}finally{closeSync(outFd);closeSync(errFd);rmSync(dir,{recursive:true,force:true});}
};
const root=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(root,'../../..'),id=randomUUID(),out=join(repo,'evidence/hara/validation-deadline/runs',id);mkdirSync(out,{recursive:true});
const sha=b=>createHash('sha256').update(b).digest('hex');
function walk(p){return readdirSync(p).sort().flatMap(n=>{const f=join(p,n),s=lstatSync(f);if(s.isSymbolicLink())throw Error('SOURCE_SYMLINK');return s.isDirectory()?walk(f):[f];});}
function hashes(){return Object.fromEntries([...walk(root),join(repo,'.github/workflows/hannie-validation-deadline.yml'),join(repo,'evidence/hara/validation-deadline/decision.json')].sort().map(p=>[relative(repo,p),sha(readFileSync(p))]));}
const commit=await runChild('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'});
const sourceHashes=hashes(),sourceSetSha256=sha(JSON.stringify(sourceHashes)),startedAt=new Date().toISOString(),tmp=mkdtempSync(join(tmpdir(),'palaco-b013-native-')),lib=join(tmp,'stall.so');
const compile=await runChild('gcc',['-shared','-fPIC','-O2','-Wall','-Werror','-o',lib,join(root,'tests/wal-stall.c'),'-ldl'],{encoding:'utf8'});writeFileSync(join(out,'compiler.stderr'),compile.stderr||'');
const client=await runChild(process.execPath,['--disable-warning=ExperimentalWarning','--test','--test-isolation=none','--test-reporter=tap','tests/client.test.mjs'],{cwd:root,encoding:'utf8'});
writeFileSync(join(out,'client-tests.tap'),client.stdout||'');writeFileSync(join(out,'client-tests.stderr'),client.stderr||'');
const clientCounts=Object.fromEntries(['tests','pass','fail','cancelled','skipped','todo'].map(k=>[k,Number(client.stdout.match(new RegExp('^# '+k+' (\\d+)$','m'))?.[1])]));
const admission=await runChild(process.execPath,['--disable-warning=ExperimentalWarning','--test','--test-isolation=none','--test-reporter=tap','tests/admission.test.mjs'],{cwd:root,encoding:'utf8'});
writeFileSync(join(out,'admission-tests.tap'),admission.stdout||'');writeFileSync(join(out,'admission-tests.stderr'),admission.stderr||'');
const admissionCounts=Object.fromEntries(['tests','pass','fail','cancelled','skipped','todo'].map(k=>[k,Number(admission.stdout.match(new RegExp('^# '+k+' (\\d+)$','m'))?.[1])]));
const issuance=await runChild(process.execPath,['--disable-warning=ExperimentalWarning','--test','--test-isolation=none','--test-reporter=tap','tests/issuance.test.mjs'],{cwd:root,encoding:'utf8',env:{...process.env,VD_TRACE_DIR:out,VD_NATIVE_LIBRARY:lib}});
writeFileSync(join(out,'issuance-tests.tap'),issuance.stdout||'');writeFileSync(join(out,'issuance-tests.stderr'),issuance.stderr||'');
const issuanceCounts=Object.fromEntries(['tests','pass','fail','cancelled','skipped','todo'].map(k=>[k,Number(issuance.stdout.match(new RegExp('^# '+k+' (\\d+)$','m'))?.[1])]));
const run=compile.status===0?await runChild(process.execPath,['--disable-warning=ExperimentalWarning','--test','--test-isolation=none','--test-concurrency=1','--test-reporter=tap','tests/contract.test.mjs'],{cwd:root,encoding:'utf8',env:{...process.env,VD_TRACE_DIR:out,VD_NATIVE_LIBRARY:lib}}):{status:null,stdout:'',stderr:'NATIVE BUILD FAILED'};
writeFileSync(join(out,'tests.tap'),run.stdout||'');writeFileSync(join(out,'tests.stderr'),run.stderr||'');
const counts=Object.fromEntries(['tests','pass','fail','cancelled','skipped','todo'].map(k=>[k,Number(run.stdout.match(new RegExp('^# '+k+' (\\d+)$','m'))?.[1])])),sourceUnchanged=JSON.stringify(hashes())===JSON.stringify(sourceHashes);
const result={kind:'VALIDATION_DEADLINE_EXECUTION_EVIDENCE',runId:id,startedAt,endedAt:new Date().toISOString(),sourceCommitAtStart:commit.stdout.trim(),sourceCommitLookup:{exit:commit.status,error:commit.error,signal:commit.signal},sourceSetSha256,sourceHashes,sourceUnchangedAfterRun:sourceUnchanged,runtime:{node:process.version,nodeBinarySha256:sha(readFileSync(process.execPath)),os:release(),platform:process.platform},nativeLibrarySha256:compile.status===0?sha(readFileSync(lib)):null,issuanceExit:issuance.status,issuanceError:issuance.error,issuanceSignal:issuance.signal,issuanceCounts,admissionExit:admission.status,admissionError:admission.error,admissionSignal:admission.signal,admissionCounts,clientExit:client.status,clientError:client.error,clientSignal:client.signal,clientCounts,compileExit:compile.status,compileError:compile.error,compileSignal:compile.signal,testExit:run.status,testError:run.error,testSignal:run.signal,counts,artifacts:Object.fromEntries(walk(out).map(p=>[relative(out,p),sha(readFileSync(p))])),checks:issuance.status===0&&!issuance.error&&!issuance.signal&&issuanceCounts.tests===18&&issuanceCounts.pass===18&&['fail','cancelled','skipped','todo'].every(k=>issuanceCounts[k]===0)&&admission.status===0&&!admission.error&&!admission.signal&&admissionCounts.tests===20&&admissionCounts.pass===20&&['fail','cancelled','skipped','todo'].every(k=>admissionCounts[k]===0)&&client.status===0&&!client.error&&!client.signal&&clientCounts.tests===13&&clientCounts.pass===13&&['fail','cancelled','skipped','todo'].every(k=>clientCounts[k]===0)&&compile.status===0&&!compile.error&&!compile.signal&&run.status===0&&!run.error&&!run.signal&&counts.tests===24&&counts.pass===24&&['fail','cancelled','skipped','todo'].every(k=>counts[k]===0)&&sourceUnchanged&&commit.status===0&&!commit.error&&!commit.signal&&/^[a-f0-9]{40}$/.test(commit.stdout.trim())?'PASS':'FAIL',scope:'New owner-approved validation-deadline synthetic profile. Separate native/crash controls; late commit allowed for an exact opt-in; independent read authority required.',measurement:'validatedAt is precommit validation; durableObservedAt is readback upperbound; no exact fsync or durable-before-expiry claim',knownBlocker:'Synthetic time/admission only; supervisor restart fails closed; restore/trust epoch and full protocol/client acceptance require separate work',independentReview:'PENDING',integration:'HOLD',production:'HOLD',proof:'NOT ISSUED',historicalEvidenceReused:false,profile:'HARA_WRITE_VALIDATION_DEADLINE_DRAFT_1'};
writeFileSync(join(out,'result.json'),JSON.stringify(result,null,2)+'\n');rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify({runId:id,sourceSetSha256,checks:result.checks,counts,clientCounts,admissionCounts,issuanceCounts}));process.exitCode=result.checks==='PASS'?0:1;

if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, 'run_id=' + id + '\n');

if(result.checks==='PASS') console.log(JSON.stringify(verifyEvidence(out,repo)));
