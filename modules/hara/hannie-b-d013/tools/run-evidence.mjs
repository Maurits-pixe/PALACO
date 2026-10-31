import {readFileSync,writeFileSync,readdirSync,lstatSync,mkdirSync,mkdtempSync,rmSync,appendFileSync,openSync,closeSync} from 'node:fs';
import {join,resolve,relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir,release} from 'node:os';
import {randomUUID,createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {evidencePassed} from './evidence-checks.mjs';
const runChild=async(command,args,options={})=>{
 const dir=mkdtempSync(join(tmpdir(),'hara-process-')),stdoutPath=join(dir,'stdout'),stderrPath=join(dir,'stderr');
 const outFd=openSync(stdoutPath,'w'),errFd=openSync(stderrPath,'w');
 try {return await new Promise(resolve=>{
  const child=spawn(command,args,{...options,stdio:['ignore',outFd,errFd]});let error=null;
  child.on('error',e=>{error={code:e.code,message:e.message};});
  child.on('close',(status,signal)=>resolve({status,signal,error,stdout:readFileSync(stdoutPath,'utf8'),stderr:readFileSync(stderrPath,'utf8')}));
 });}finally{closeSync(outFd);closeSync(errFd);rmSync(dir,{recursive:true,force:true});}
};
const root=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(root,'../../..'),id=randomUUID(),out=join(repo,'evidence/hara/b-d013/runs',id);mkdirSync(out,{recursive:true});
const sha=b=>createHash('sha256').update(b).digest('hex');
function walk(p){return readdirSync(p).sort().flatMap(n=>{const f=join(p,n),s=lstatSync(f);if(s.isSymbolicLink())throw Error('SOURCE_SYMLINK');return s.isDirectory()?walk(f):[f];});}
function hashes(){return Object.fromEntries([...walk(root),join(repo,'.github/workflows/hannie-b-d013.yml'),join(repo,'evidence/hara/b-d013/source-manifest.json')].sort().map(p=>[relative(repo,p),sha(readFileSync(p))]));}
const commit=await runChild('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'});
const sourceHashes=hashes(),sourceSetSha256=sha(JSON.stringify(sourceHashes)),startedAt=new Date().toISOString(),tmp=mkdtempSync(join(tmpdir(),'palaco-b013-native-')),lib=join(tmp,'stall.so');
const compile=await runChild('gcc',['-shared','-fPIC','-O2','-Wall','-Werror','-o',lib,join(root,'tests/wal-stall.c'),'-ldl'],{encoding:'utf8'});writeFileSync(join(out,'compiler.stderr'),compile.stderr||'');
const run=compile.status===0?await runChild(process.execPath,['--disable-warning=ExperimentalWarning','--test','--test-isolation=none','--test-concurrency=1','--test-reporter=tap','tests/commit.test.mjs'],{cwd:root,encoding:'utf8',env:{...process.env,B013_TRACE_DIR:out,B013_NATIVE_LIBRARY:lib}}):{status:null,stdout:'',stderr:'NATIVE BUILD FAILED'};
writeFileSync(join(out,'tests.tap'),run.stdout||'');writeFileSync(join(out,'tests.stderr'),run.stderr||'');
const counts=Object.fromEntries(['tests','pass','fail','cancelled','skipped','todo'].map(k=>[k,Number(run.stdout.match(new RegExp('^# '+k+' (\\d+)$','m'))?.[1])])),sourceUnchanged=JSON.stringify(hashes())===JSON.stringify(sourceHashes);
const result={kind:'B_D013_EXECUTION_EVIDENCE',runId:id,startedAt,endedAt:new Date().toISOString(),sourceCommitAtStart:commit.stdout.trim(),sourceCommitLookup:{exit:commit.status,error:commit.error,signal:commit.signal},sourceSetSha256,sourceHashes,sourceUnchangedAfterRun:sourceUnchanged,runtime:{node:process.version,nodeBinarySha256:sha(readFileSync(process.execPath)),os:release(),platform:process.platform},nativeLibrarySha256:compile.status===0?sha(readFileSync(lib)):null,compileExit:compile.status,compileError:compile.error,compileSignal:compile.signal,testExit:run.status,testError:run.error,testSignal:run.signal,counts,artifacts:Object.fromEntries(walk(out).map(p=>[relative(out,p),sha(readFileSync(p))])),checks:evidencePassed({compile,run,counts,sourceUnchanged,commit})?'PASS':'FAIL',scope:'New B transaction, actual SIGKILL before/after COMMIT, fresh-process read-only reconstruction, revoke ordering, lost ACK, native late WAL withheld with counterevidence preserved.',measurement:'Post-crash readback upperbounds, no precommit sample as decisionAt, no exact fsync timestamp',knownBlocker:'Late durability can retain a nonaccepted effect; upperbound receipt measurement requires independent review',independentReview:'PENDING',integration:'HOLD',production:'HOLD',proof:'NOT ISSUED',denySuiteEvidenceReused:false};
writeFileSync(join(out,'result.json'),JSON.stringify(result,null,2)+'\n');rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify({runId:id,sourceSetSha256,checks:result.checks,counts}));process.exitCode=result.checks==='PASS'?0:1;

if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, 'run_id=' + id + '\n');
