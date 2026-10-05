import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {execute,recover,revoke} from '../src/index.mjs';
import {fixture,inspect,mutate,state,counts} from './fixture.mjs';
const trace=(n,r)=>{if(process.env.B013_TRACE_DIR)writeFileSync(join(process.env.B013_TRACE_DIR,n+'.json'),JSON.stringify(r,null,2)+'\n');};
const zero={audit:0,decisions:0,events:0,versions:0,receipts:0},one={audit:1,decisions:1,events:1,versions:1,receipts:1};
test('B01 actual SIGKILL after COMMIT and new process reconstruct all atomic rows before expiry',async t=>{
 const f=fixture(t),r=await execute(f.path,f.context,f.request);assert.equal(r.status,'SUCCEEDED');assert.equal(r.writer.signal,'SIGKILL');assert.notEqual(r.readProcess.pid,r.writer.pid);assert.deepEqual(counts(f.path),one);
 assert.equal(inspect(f.path,d=>d.prepare('SELECT consumed FROM approvals').get().consumed),1);assert.ok(r.receipt.decisionAt<=r.receipt.effectAt);assert.ok(r.receipt.effectAt<f.expiry);assert.equal(r.receipt.measurement,'AFTER_CRASH_READBACK_UPPER_BOUNDS');assert.equal(r.receipt.twoDurableMoments,false);trace('B01',r);
});
test('B02 SIGKILL before COMMIT loses all effects and recovery never writes',async t=>{
 const f=fixture(t),before=state(f.path),r=await execute(f.path,f.context,f.request,{B013_TEST_PHASE:'beforeCommit'});assert.equal(r.status,'RESULT_UNKNOWN');assert.equal(r.writer.signal,'SIGKILL');assert.deepEqual(counts(f.path),zero);assert.equal(state(f.path),before);assert.equal((await recover(f.path,f.context,f.request)).status,'RESULT_UNKNOWN');assert.equal(state(f.path),before);trace('B02',r);
});
test('B03 false ACK before durability cannot be success',async t=>{
 const f=fixture(t),before=state(f.path),r=await execute(f.path,f.context,f.request,{B013_TEST_PHASE:'fakeAckBeforeCommit'});assert.equal(r.writer.message.status,'SUCCEEDED');assert.equal(r.status,'RESULT_UNKNOWN');assert.equal(state(f.path),before);trace('B03',r);
});
test('B04 crash-surviving revoke before decision blocks effect',async t=>{
 const f=fixture(t),rev=await revoke(f.path,f.context,f.request.grantId);assert.equal(rev.writer.signal,'SIGKILL');assert.equal(inspect(f.path,d=>d.prepare('SELECT state FROM grants').get().state),'REVOKED');const before=state(f.path),r=await execute(f.path,f.context,f.request);assert.equal(r.status,'DENIED');assert.equal(r.code,'CONSENT_INACTIVE');assert.equal(state(f.path),before);assert.equal(counts(f.path).events,0);trace('B04',{rev,r});
});
test('B05 revoke after commit keeps historical effect but blocks new disclosure and replay',async t=>{
 const f=fixture(t);assert.equal((await execute(f.path,f.context,f.request)).status,'SUCCEEDED');await revoke(f.path,f.context,f.request.grantId);const before=state(f.path),r=await recover(f.path,f.context,f.request);assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'REVOKED');assert.equal(r.event,undefined);assert.equal(r.receipt,undefined);assert.equal((await execute(f.path,f.context,f.request)).status,'COMMITTED_RESULT_WITHHELD');assert.equal(state(f.path),before);assert.equal(counts(f.path).events,1);
 inspect(f.path,d=>{const a=d.prepare('SELECT * FROM audit ORDER BY seq').all();assert.equal(a[0].kind,'DECISION');assert.equal(a[1].kind,'REVOKE');assert.ok(a[0].seq<a[1].seq);});trace('B05',r);
});
test('B06 lost ACK after durability reconstructs only with no second write',async t=>{
 const f=fixture(t),r=await execute(f.path,f.context,f.request);assert.equal(r.writer.message,undefined);assert.equal(r.writer.signal,'SIGKILL');assert.equal(r.status,'SUCCEEDED');const before=state(f.path);for(let i=0;i<2;i++){assert.equal((await recover(f.path,f.context,f.request)).status,'SUCCEEDED');assert.equal((await execute(f.path,f.context,f.request)).status,'SUCCEEDED');}assert.equal(state(f.path),before);assert.deepEqual(counts(f.path),one);trace('B06',r);
});
for(const [n,edit] of [['digest',r=>({...r,title:'Changed'})],['generation',r=>({...r,generation:2})]])test('B07 wrong '+n+' cannot consume approval or write',async t=>{const f=fixture(t),before=state(f.path),r=await execute(f.path,f.context,edit(f.request));assert.equal(r.status,'DENIED');assert.equal(state(f.path),before);});
test('B08 context isolation before write and during recovery',async t=>{const f=fixture(t);assert.equal((await execute(f.path,{...f.context,session:'other'},f.request)).status,'DENIED');assert.deepEqual(counts(f.path),zero);assert.equal((await execute(f.path,f.context,f.request)).status,'SUCCEEDED');assert.equal((await recover(f.path,{...f.context,tenant:'other'},f.request)).status,'RESULT_UNKNOWN');});
test('B09 corrupt receipt is not success and replay cannot repair it',async t=>{const f=fixture(t);assert.equal((await execute(f.path,f.context,f.request)).status,'SUCCEEDED');mutate(f.path,d=>d.prepare("UPDATE receipts SET binding='{}'").run());const before=state(f.path);assert.equal((await recover(f.path,f.context,f.request)).code,'BINDING_MISMATCH');assert.equal((await execute(f.path,f.context,f.request)).status,'RESULT_UNKNOWN');assert.equal(state(f.path),before);});
test('B10 real SQLite lock wait past expiry rejects inside transaction',async t=>{const f=fixture(t,250),lock=new DatabaseSync(f.path);lock.exec('BEGIN IMMEDIATE');const running=execute(f.path,f.context,f.request);await new Promise(r=>setTimeout(r,350));lock.exec('ROLLBACK');lock.close();const r=await running;assert.equal(r.status,'DENIED');assert.equal(r.code,'CONSENT_INACTIVE');assert.deepEqual(counts(f.path),zero);trace('B10',r);});
test('B11 real concurrent duplicate writers create only one atomic effect',async t=>{const f=fixture(t),[a,b]=await Promise.all([execute(f.path,f.context,f.request),execute(f.path,f.context,f.request)]);assert.equal(a.status,'SUCCEEDED');assert.equal(b.status,'SUCCEEDED');assert.deepEqual(counts(f.path),one);trace('B11',{a,b});});
test('B12 native WAL stall crosses expiry: precommit sample is not timely success and recovery does not replay',async t=>{
 assert.ok(process.env.B013_NATIVE_LIBRARY);const f=fixture(t,450),env={LD_PRELOAD:process.env.B013_NATIVE_LIBRARY,B013_WAL_PATH:f.path+'-wal',B013_WAL_ARM:join(f.dir,'arm'),B013_NATIVE_TRACE:join(f.dir,'native.jsonl')};const r=await execute(f.path,f.context,f.request,env),native=readFileSync(env.B013_NATIVE_TRACE,'utf8').trim().split('\n').map(JSON.parse);assert.equal(native.length,1);assert.ok(native[0].startMs<f.expiry);assert.ok(native[0].endMs>f.expiry);assert.equal(r.status,'COMMITTED_RESULT_WITHHELD');assert.equal(r.code,'DEADLINE_NOT_PROVEN');assert.equal(r.event,undefined);assert.equal(r.receipt,undefined);const sample=inspect(f.path,d=>d.prepare('SELECT precommit_observed_at FROM decisions').get().precommit_observed_at);assert.ok(sample<f.expiry);assert.deepEqual(counts(f.path),one);const before=state(f.path);assert.equal((await recover(f.path,f.context,f.request)).status,'COMMITTED_RESULT_WITHHELD');assert.equal(state(f.path),before);trace('B12',{r,native,expiry:f.expiry,precommitObservedAt:sample,lateEffectExists:true,acceptedTimelySuccess:false});
});
test('B13 concurrent revoke and mutation share authoritative commit order',async t=>{
 const f=fixture(t),[mutation,revocation]=await Promise.all([execute(f.path,f.context,f.request),revoke(f.path,f.context,f.request.grantId)]),a=inspect(f.path,d=>d.prepare('SELECT kind FROM audit ORDER BY seq').all());if(a[0].kind==='REVOKE'){assert.equal(counts(f.path).events,0);assert.equal(mutation.status,'DENIED');}else{assert.equal(a[0].kind,'DECISION');assert.equal(a[1].kind,'REVOKE');assert.equal(counts(f.path).events,1);}const r=await recover(f.path,f.context,f.request);assert.notEqual(r.status,'SUCCEEDED');assert.equal(r.event,undefined);trace('B13',{mutation,revocation,order:a,r});
});

test('B14 actual SIGKILL inside native COMMIT WAL write cannot survive as success',async t=>{
 assert.ok(process.env.B013_NATIVE_LIBRARY);const f=fixture(t),before=state(f.path),env={LD_PRELOAD:process.env.B013_NATIVE_LIBRARY,B013_WAL_PATH:f.path+'-wal',B013_WAL_ARM:join(f.dir,'arm'),B013_NATIVE_TRACE:join(f.dir,'native.jsonl'),B013_NATIVE_MODE:'kill-before-wal-write'};
 const r=await execute(f.path,f.context,f.request,env),native=JSON.parse(readFileSync(env.B013_NATIVE_TRACE,'utf8').trim());
 assert.equal(native.kind,'NATIVE_COMMIT_INTERRUPT');assert.equal(native.beforeWalWrite,true);assert.equal(r.writer.signal,'SIGKILL');assert.equal(r.status,'RESULT_UNKNOWN');assert.deepEqual(counts(f.path),zero);assert.equal(state(f.path),before);assert.equal((await recover(f.path,f.context,f.request)).status,'RESULT_UNKNOWN');assert.equal(state(f.path),before);trace('B14',{r,native});
});
