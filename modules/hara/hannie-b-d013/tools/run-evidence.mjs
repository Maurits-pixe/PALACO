import {readFileSync,writeFileSync,readdirSync,lstatSync,mkdirSync,mkdtempSync,rmSync,openSync,closeSync} from 'node:fs';
import {join,resolve,relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir,release} from 'node:os';
import {randomUUID,createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
const root=fileURLToPath(new URL('../',import.meta.url)),repo=resolve(root,'../../..'),id=randomUUID(),out=join(repo,'evidence/hara/b-d013/runs',id);mkdirSync(out,{recursive:true});
const sha=b=>createHash('sha256').update(b).digest('hex');
function walk(p){return readdirSync(p).sort().flatMap(n=>{const f=join(p,n),s=lstatSync(f);if(s.isSymbolicLink())throw Error('SOURCE_SYMLINK');return s.isDirectory()?walk(f):[f];});}
function hashes(){return Object.fromEntries([...walk(root),join(repo,'.github/workflows/hannie-b-d013.yml'),join(repo,'evidence/hara/b-d013/source-manifest.json')].sort().map(p=>[relative(repo,p),sha(readFileSync(p))]));}
const sourceHashes=hashes(),sourceSetSha256=sha(JSON.stringify(sourceHashes)),startedAt=new Date().toISOString(),tmp=mkdtempSync(join(tmpdir(),'palaco-b013-native-')),lib=join(tmp,'stall.so');
const compilerFd=openSync(join(out,'compiler.stderr'),'w');
let compile;
try {compile=spawnSync('gcc',['-shared','-fPIC','-O2','-Wall','-Werror','-o',lib,join(root,'tests/wal-stall.c'),'-ldl'],{stdio:['ignore','ignore',compilerFd]});}
finally {closeSync(compilerFd);}
// Preserve raw output without relying on nested subprocess pipes.
// Default isolation stays unchanged; the explicit fallback is recorded per run.
const isolation=process.env.B013_TEST_ISOLATION ?? 'process';
if(!['process','none'].includes(isolation)) throw Error('INVALID_TEST_ISOLATION');
const tapPath=join(out,'tests.tap'),stderrPath=join(out,'tests.stderr');
const tapFd=openSync(tapPath,'w'),stderrFd=openSync(stderrPath,'w');
let run;
try {
 run=compile.status===0?spawnSync(process.execPath,['--disable-warning=ExperimentalWarning','--test-isolation='+isolation,'--test','--test-concurrency=1','--test-reporter=tap','tests/commit.test.mjs'],{cwd:root,stdio:['ignore',tapFd,stderrFd],env:{...process.env,B013_TRACE_DIR:out,B013_NATIVE_LIBRARY:lib}}):{status:null,error:new Error('NATIVE BUILD FAILED')};
} finally {closeSync(tapFd);closeSync(stderrFd);}
const stdout=readFileSync(tapPath,'utf8');
const counts=Object.fromEntries(['tests','pass','fail','cancelled','skipped','todo'].map(k=>[k,Number(stdout.match(new RegExp('^# '+k+' (\\d+)$','m'))?.[1]||0)])),sourceUnchanged=JSON.stringify(hashes())===JSON.stringify(sourceHashes);
const result={kind:'B_D013_EXECUTION_EVIDENCE',runId:id,startedAt,endedAt:new Date().toISOString(),sourceCommitAtStart:spawnSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'}).stdout.trim(),sourceSetSha256,sourceHashes,sourceUnchangedAfterRun:sourceUnchanged,runtime:{node:process.version,nodeBinarySha256:sha(readFileSync(process.execPath)),os:release(),platform:process.platform},nativeLibrarySha256:compile.status===0?sha(readFileSync(lib)):null,compileExit:compile.status,compileSignal:compile.signal??null,compileSpawnError:compile.error?{code:compile.error.code??null,message:compile.error.message}:null,expectedTests:22,testExit:run.status,testSignal:run.signal??null,testSpawnError:run.error?{code:run.error.code??null,message:run.error.message}:null,testIsolation:isolation,counts,artifacts:Object.fromEntries(walk(out).map(p=>[relative(out,p),sha(readFileSync(p))])),checks:compile.status===0&&!compile.error&&run.status===0&&!run.signal&&!run.error&&counts.tests===counts.pass&&counts.tests===22&&!counts.fail&&!counts.skipped&&!counts.cancelled&&!counts.todo&&sourceUnchanged?'PASS':'FAIL',scope:'New B transaction, actual SIGKILL before/after COMMIT, fresh-process read-only reconstruction, revoke ordering, lost ACK, native late WAL withheld with counterevidence preserved.',measurement:'Post-crash readback upperbounds, no precommit sample as decisionAt, no exact fsync timestamp',knownBlocker:'Late durability can retain a nonaccepted effect; upperbound receipt measurement requires independent review',independentReview:'PENDING',integration:'HOLD',production:'HOLD',proof:'NOT ISSUED',denySuiteEvidenceReused:false};
writeFileSync(join(out,'result.json'),JSON.stringify(result,null,2)+'\n');rmSync(tmp,{recursive:true,force:true});console.log(JSON.stringify({runId:id,sourceSetSha256,checks:result.checks,counts}));process.exitCode=result.checks==='PASS'?0:1;
