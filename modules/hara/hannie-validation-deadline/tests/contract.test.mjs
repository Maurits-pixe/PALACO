import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {DatabaseSync} from 'node:sqlite';
import {execute,recover,revoke} from '../src/index.mjs';
import {presentResult} from '../src/client.mjs';
import {PROFILE,withinValidationWindow} from '../src/value.mjs';
import {fixture,inspect,mutate,state,counts} from './fixture.mjs';
const zero={audit:0,decisions:0,events:0,versions:0,receipts:0};
const one={audit:1,decisions:1,events:1,versions:1,receipts:1};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const run=(f,env={})=>execute(f.path,f.context,f.request,{readCapability:f.readCapability,trustedHarnessEnvironment:env});
const read=f=>recover(f.path,f.context,f.request,f.readCapability);
const trace=(id,data)=>{if(process.env.VD_TRACE_DIR)writeFileSync(join(process.env.VD_TRACE_DIR,id+'.json'),JSON.stringify(data,null,2)+'\n');};
const stall=f=>({LD_PRELOAD:process.env.VD_NATIVE_LIBRARY,VD_WAL_PATH:f.path+'-wal',VD_WAL_ARM:join(f.dir,'arm'),VD_NATIVE_TRACE:join(f.dir,'native.jsonl')});

test('N01 exact new profile, one crash-surviving decision/effect and versioned receipt',async t=>{
 const f=fixture(t),r=await run(f);assert.equal(r.status,'COMMITTED');assert.equal(r.writer.signal,'SIGKILL');assert.notEqual(r.writer.pid,r.readProcess.pid);assert.deepEqual(counts(f.path),one);
 assert.equal(r.receipt.contractProfile,PROFILE);assert.equal(r.receipt.receiptVersion,1);assert.equal(r.receipt.deadlineSatisfied,'VALIDATION_DEADLINE_ONLY');assert.ok(r.receipt.validatedAt<f.expiry);assert.ok(r.receipt.validatedAt<=r.receipt.durableObservedAt);assert.equal(r.receipt.exactDurableAt,'UNKNOWN');assert.equal(r.receipt.decisionAt,undefined);assert.equal(r.receipt.effectAt,undefined);trace('N01',r);
});
test('N02 real SQLite lockwait crosses write expiry: entire transaction rolled back',async t=>{
 const f=fixture(t,{lifetime:250}),db=new DatabaseSync(f.path);db.exec('BEGIN IMMEDIATE');const running=run(f);await wait(350);db.exec('ROLLBACK');db.close();const r=await running;assert.equal(r.status,'DENIED');assert.equal(r.code,'VALIDATION_DEADLINE_EXPIRED');assert.deepEqual(counts(f.path),zero);assert.equal(inspect(f.path,d=>d.prepare('SELECT consumed FROM approvals').get().consumed),0);trace('N02',r);
});
test('N03 approval expiry earlier than grant still denies mutation',async t=>{
 const f=fixture(t,{approvalLifetime:1});await wait(10);const r=await run(f);assert.equal(r.status,'DENIED');assert.equal(r.code,'VALIDATION_DEADLINE_EXPIRED');assert.deepEqual(counts(f.path),zero);trace('N03',r);
});
test('N04 new-profile opt-in allows late durable commit, separate read authority releases explicit receipt',async t=>{
 assert.ok(process.env.VD_NATIVE_LIBRARY);const f=fixture(t,{lifetime:450}),env=stall(f),r=await run(f,env),native=readFileSync(env.VD_NATIVE_TRACE,'utf8').trim().split('\n').map(JSON.parse);
 assert.equal(native.length,1);assert.equal(native[0].delayMs,900);assert.ok(native[0].startMs<f.expiry);assert.ok(native[0].endMs>f.expiry);assert.ok(native[0].endMs-native[0].startMs>=900);
 assert.equal(r.status,'COMMITTED');assert.ok(r.receipt.validatedAt<f.expiry);assert.equal(r.receipt.observedAfterExpiry,true);assert.equal(r.receipt.deadlineSatisfied,'VALIDATION_DEADLINE_ONLY');assert.equal(r.receipt.exactDurableAt,'UNKNOWN');assert.deepEqual(counts(f.path),one);const before=state(f.path);assert.equal((await read(f)).status,'COMMITTED');assert.equal(state(f.path),before);const clientView=presentResult(r,f.context,f.request);assert.equal(clientView.state,'CONFIRMED');assert.ok(clientView.timing.includes('na verlopen'));trace('N04',{r,native,expiry:f.expiry,lateEffectExists:true,d013Conformance:false,newProfile:true,clientView});
});
test('N05 SIGKILL after validation before commit leaves no durable effect or approval consumption',async t=>{
 const f=fixture(t),before=state(f.path),r=await run(f,{VD_TEST_PHASE:'beforeCommit'});assert.equal(r.status,'RESULT_UNKNOWN');assert.equal(r.writer.signal,'SIGKILL');assert.equal(state(f.path),before);assert.deepEqual(counts(f.path),zero);trace('N05',r);
});
test('N06 lost ACK and replay reconstruct without second write or approval consumption',async t=>{
 const f=fixture(t),r=await run(f);assert.equal(r.status,'COMMITTED');assert.equal(r.writer.message.status,'WRITE_ATTEMPT');const before=state(f.path);assert.equal((await run(f)).status,'COMMITTED');assert.equal((await read(f)).status,'COMMITTED');assert.equal(state(f.path),before);assert.deepEqual(counts(f.path),one);trace('N06',r);
});
test('N07 fake success ACK before durability is ignored',async t=>{
 const f=fixture(t),r=await run(f,{VD_TEST_PHASE:'fakeAckBeforeCommit'});assert.equal(r.writer.message.status,'COMMITTED');assert.equal(r.status,'RESULT_UNKNOWN');assert.deepEqual(counts(f.path),zero);trace('N07',r);
});
test('N08 durable revoke first blocks effects',async t=>{
 const f=fixture(t);await revoke(f.path,f.context,f.request.grantId);const before=state(f.path),r=await run(f);assert.equal(r.status,'DENIED');assert.equal(r.code,'CONSENT_INACTIVE');assert.equal(counts(f.path).events,0);assert.equal(state(f.path),before);trace('N08',r);
});
test('N09 revoke requested during commit stall waits for ordering and blocks subsequent payload',async t=>{
 const f=fixture(t),env={...stall(f),VD_WRITE_READY:join(f.dir,'write-ready')},writing=run(f,env);for(let i=0;i<300&&!existsSync(env.VD_WRITE_READY);i++)await wait(5);
 assert.ok(existsSync(env.VD_WRITE_READY));await wait(100);assert.equal(existsSync(env.VD_NATIVE_TRACE),false);
 const revokeRequestedAt=Date.now(),revoking=revoke(f.path,f.context,f.request.grantId);const [mutation,rev]=await Promise.all([writing,revoking]);assert.equal(rev.writer.signal,'SIGKILL');
 const order=inspect(f.path,d=>d.prepare('SELECT kind FROM audit ORDER BY seq').all().map(x=>x.kind));assert.deepEqual(order,['DECISION','REVOKE']);assert.equal(counts(f.path).events,1);const r=await read(f);assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'WRITE_REVOKED');assert.equal(r.event,undefined);const native=JSON.parse(readFileSync(env.VD_NATIVE_TRACE,'utf8').trim());assert.ok(native.startMs<=revokeRequestedAt&&revokeRequestedAt<native.endMs);trace('N09',{mutation,rev,order,r,native,revokeRequestedAt});
});
test('N10 durable revoke after commit withholds new payload and retains history',async t=>{
 const f=fixture(t);await run(f);await revoke(f.path,f.context,f.request.grantId);const before=state(f.path),r=await read(f);assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'WRITE_REVOKED');assert.equal(r.event,undefined);assert.equal(r.receipt,undefined);assert.equal(counts(f.path).events,1);assert.equal(state(f.path),before);trace('N10',r);
});
test('N11 independent read authority expiring during locked release wait blocks contents',async t=>{
 const f=fixture(t,{readLifetime:1000});await run(f);await wait(Math.max(0,f.readExpiry-Date.now()-150));process.env.VD_READ_READY=join(f.dir,'read-ready');
 try{const r=await read(f);assert.ok(existsSync(process.env.VD_READ_READY));assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'READ_AUTHORITY_REQUIRED');assert.equal(r.event,undefined);trace('N11',r);}finally{delete process.env.VD_READ_READY;}
});
test('N12 digest, context, generation and corrupt receipt cannot produce payload',async t=>{
 const f=fixture(t);await run(f);const before=state(f.path);
 for(const [context,request] of [[f.context,{...f.request,title:'changed'}],[{...f.context,tenant:'other'},f.request],[f.context,{...f.request,generation:2}]]){
  const r=await recover(f.path,context,request,f.readCapability);assert.equal(r.status,'RESULT_UNKNOWN');assert.equal(r.event,undefined);
 }assert.equal(state(f.path),before);mutate(f.path,d=>d.exec("UPDATE receipts SET binding='{}'"));assert.equal((await read(f)).code,'BINDING_MISMATCH');trace('N12',{stateUnchangedBeforeCorruption:true,result:await read(f)});
});
test('N13 fresh supervisor cannot infer trusted validation from database timestamp',async t=>{
 const f=fixture(t);await run(f);const before=state(f.path),output=join(f.dir,'fresh-reader.json');
 const script=`import {writeFileSync} from 'node:fs';import {recover} from ${JSON.stringify(new URL('../src/index.mjs',import.meta.url).href)};writeFileSync(${JSON.stringify(output)},JSON.stringify(await recover(${JSON.stringify(f.path)},${JSON.stringify(f.context)},${JSON.stringify(f.request)},${JSON.stringify(f.readCapability)})));`;
 await new Promise((resolve,reject)=>{const p=spawn(process.execPath,['--disable-warning=ExperimentalWarning','--input-type=module','-e',script],{stdio:'ignore'});p.on('error',reject);p.on('close',code=>code===0?resolve():reject(Error('reader '+code)));});
 const r=JSON.parse(readFileSync(output,'utf8'));assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'TIME_TRUST_UNAVAILABLE');assert.equal(r.event,undefined);assert.equal(state(f.path),before);trace('N13',r);
});
test('N14 no implicit upgrade: profile and opt-in required on request, grant and exact approval',async t=>{
 const f=fixture(t),before=state(f.path);
 await assert.rejects(()=>execute(f.path,f.context,{...f.request,finishAfterExpiry:false}),/PROFILE_OPT_IN_REQUIRED/);
 await assert.rejects(()=>execute(f.path,f.context,{...f.request,contractProfile:'old'}),/PROFILE_OPT_IN_REQUIRED/);assert.equal(state(f.path),before);
 mutate(f.path,d=>d.exec('UPDATE grants SET finish_after_expiry=0'));assert.equal((await run(f)).code,'PROFILE_OPT_IN_REQUIRED');
 mutate(f.path,d=>d.exec('UPDATE grants SET finish_after_expiry=1; UPDATE approvals SET finish_after_expiry=0'));assert.equal((await run(f)).code,'PROFILE_OPT_IN_REQUIRED');assert.deepEqual(counts(f.path),zero);trace('N14',{noImplicitUpgrade:true});
});
test('N15 legacy request shape is rejected and new receipts never claim old durable deadline',async t=>{
 const f=fixture(t),legacy={...f.request};delete legacy.contractProfile;delete legacy.finishAfterExpiry;await assert.rejects(()=>execute(f.path,f.context,legacy),/INVALID_INPUT/);
 const r=await run(f);assert.equal(r.receipt.contractProfile,PROFILE);assert.equal(r.status,'COMMITTED');assert.equal(r.receipt.decisionAt,undefined);assert.equal(r.receipt.effectAt,undefined);assert.equal(r.receipt.deadlineSatisfied,'VALIDATION_DEADLINE_ONLY');trace('N15',r);
});
test('N16 API error after durable commit is reconstructed or withheld, never retried blindly',async t=>{
 const f=fixture(t),r=await run(f,{VD_TEST_PHASE:'errorAfterCommit'});assert.equal(r.writer.message.status,'DENIED');assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'TIME_TRUST_UNAVAILABLE');assert.deepEqual(counts(f.path),one);const before=state(f.path);const replay=await run(f);assert.equal(replay.status,'COMMITTED_RESULT_WITHHELD');assert.equal(state(f.path),before);trace('N16',{r,replay});
});
test('N17 no read capability or revoked independent read grant cannot reveal event contents',async t=>{
 const f=fixture(t),r=await execute(f.path,f.context,f.request);assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'READ_AUTHORITY_REQUIRED');assert.equal(r.event,undefined);assert.equal((await read(f)).status,'COMMITTED');
 await revoke(f.path,f.context,f.readCapability.grantId,{readGrant:true});const before=state(f.path),blocked=await read(f);assert.equal(blocked.status,'COMMITTED_RESULT_WITHHELD');assert.equal(blocked.event,undefined);assert.equal(state(f.path),before);trace('N17',{r,blocked});
});
test('N18 native SIGKILL during WAL write is not a durable result',async t=>{
 const f=fixture(t),env={...stall(f),VD_NATIVE_MODE:'kill-before-wal-write'},before=state(f.path),r=await run(f,env);assert.equal(r.status,'RESULT_UNKNOWN');assert.equal(r.writer.signal,'SIGKILL');assert.equal(state(f.path),before);assert.deepEqual(counts(f.path),zero);trace('N18',{r,native:JSON.parse(readFileSync(env.VD_NATIVE_TRACE,'utf8'))});
});
test('N19 wall clock rollback cannot revive an expired independent read grant',async t=>{
 const f=fixture(t,{readLifetime:250});await run(f);await wait(300);const original=Date.now,options=process.env.NODE_OPTIONS;
 Date.now=()=>f.readExpiry-1000;process.env.NODE_OPTIONS='--import='+fileURLToPath(new URL('./rollback-clock.mjs',import.meta.url));
 try{const r=await read(f);assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.event,undefined);trace('N19',r);}finally{Date.now=original;if(options===undefined)delete process.env.NODE_OPTIONS;else process.env.NODE_OPTIONS=options;}
});

test('N20 independently supplied read capability must match owner, session, calendar and generation',async t=>{
 const f=fixture(t);await run(f);const before=state(f.path);
 const r=await recover(f.path,f.context,f.request,{...f.readCapability,generation:2});assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.event,undefined);assert.equal(state(f.path),before);
 mutate(f.path,d=>d.exec("UPDATE read_grants SET session='other'"));const blocked=await read(f);assert.equal(blocked.status,'COMMITTED_RESULT_WITHHELD');assert.equal(blocked.event,undefined);trace('N20',{r,blocked});
});
test('N21 audit binding and malformed persisted decisions fail unknown, never success or replay repair',async t=>{
 const f=fixture(t);await run(f);mutate(f.path,d=>d.exec("UPDATE audit SET grant_id='other' WHERE kind='DECISION'"));assert.equal((await read(f)).code,'BINDING_MISMATCH');
 mutate(f.path,d=>d.exec("UPDATE decisions SET binding='not JSON'"));const before=state(f.path),r=await read(f);assert.equal(r.status,'RESULT_UNKNOWN');assert.equal(r.event,undefined);assert.equal((await run(f)).status,'RESULT_UNKNOWN');assert.equal(state(f.path),before);trace('N21',r);
});
test('N22 concurrent duplicate processes consume one approval and commit one effect',async t=>{
 const f=fixture(t),results=await Promise.all([run(f),run(f)]);assert.deepEqual(counts(f.path),one);assert.equal((await read(f)).status,'COMMITTED');assert.ok(results.every(r=>['COMMITTED','COMMITTED_RESULT_WITHHELD'].includes(r.status)));assert.equal(inspect(f.path,d=>d.prepare('SELECT consumed FROM approvals').get().consumed),1);trace('N22',results);
});
test('N23 validation boundary is strictly less than both expiries, including equality',()=>{
 assert.equal(withinValidationWindow(999,1000,2000),true);assert.equal(withinValidationWindow(1000,1000,2000),false);assert.equal(withinValidationWindow(1001,1000,2000),false);assert.equal(withinValidationWindow(1000,2000,1000),false);assert.equal(withinValidationWindow(NaN,2000,2000),false);trace('N23',{strictBoundary:true});
});

test('N24 observed clock advance past read expiry before send must withhold payload',async t=>{
 const f=fixture(t);assert.equal((await run(f)).status,'COMMITTED');
 const bootstrap=join(f.dir,'advance-clock.mjs');
 writeFileSync(bootstrap,`const original=Date.now;let count=0;Date.now=()=>{if(new Error().stack.includes('src/worker.mjs')&&++count>=3)return ${f.readExpiry+1000};return original();};`);
 const previous=process.env.NODE_OPTIONS;process.env.NODE_OPTIONS='--import='+bootstrap;
 try{const r=await read(f);assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'READ_AUTHORITY_REQUIRED');assert.equal(r.event,undefined);assert.equal(r.receipt,undefined);trace('N24',r);}finally{if(previous===undefined)delete process.env.NODE_OPTIONS;else process.env.NODE_OPTIONS=previous;}
});
