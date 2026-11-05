import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture,inspect,mutate,state} from './fixture.mjs';
import {recordConsentSelection} from '../src/client.mjs';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {execute,revoke} from '../src/index.mjs';
import {prepareChallenge,confirmChallenge,inspectApproval,fixtureCall} from './approval-store.mjs';
const trace=(id,data)=>{if(process.env.VD_TRACE_DIR)writeFileSync(join(process.env.VD_TRACE_DIR,id+'.json'),JSON.stringify(data,null,2)+'\n');};
const yes={approveExactRequest:true,allowLateCompletion:true};
async function setup(t,options={}){const f=fixture(t,{...options,provisionApproval:false}),prepared=await prepareChallenge(f);assert.equal(prepared.message.status,'SYNTHETIC_CHALLENGE');const c=prepared.message;return {f,c,selection:recordConsentSelection(c.preview,yes,Date.now())};}
const n=f=>inspect(f.path,d=>d.prepare('SELECT count(*) n FROM approvals').get().n);
test('I01 fixture challenge and exact approval are separate; runtime still revalidates',async t=>{
 const {f,c,selection}=await setup(t);assert.equal(n(f),0);const r=await confirmChallenge(f,c.challengeId,selection,yes);assert.equal(r.writer.signal,'SIGKILL');assert.equal(r.read.message.status,'SYNTHETIC_APPROVAL_RECONSTRUCTED');assert.equal(r.read.message.realAuthorityGranted,false);assert.equal(n(f),1);const result=await execute(f.path,f.context,f.request,{readCapability:f.readCapability});assert.equal(result.status,'COMMITTED');trace('I01',{r,result});
});
test('I02 crash before commit leaves challenge open and no approval; readback writes nothing',async t=>{
 const {f,c,selection}=await setup(t),before=state(f.path),r=await confirmChallenge(f,c.challengeId,selection,yes,{phase:'beforeCommit'});assert.equal(r.writer.signal,'SIGKILL');assert.equal(r.read.message.status,'NO_APPROVAL');assert.equal(n(f),0);assert.equal(state(f.path),before);assert.equal(inspect(f.path,d=>d.prepare('SELECT state FROM fixture_challenges').get().state),'OPEN');trace('I02',r);
});
test('I03 lost ACK after durable commit reconstructs consumed challenge and approval',async t=>{
 const {f,c,selection}=await setup(t),r=await confirmChallenge(f,c.challengeId,selection,yes);assert.equal(r.writer.message.status,'FIXTURE_WRITE_ATTEMPT');assert.equal(r.writer.signal,'SIGKILL');assert.equal(r.read.message.status,'SYNTHETIC_APPROVAL_RECONSTRUCTED');const before=state(f.path);await inspectApproval(f,c.challengeId);assert.equal(state(f.path),before);trace('I03',r);
});
test('I04 real concurrent confirmation processes issue exactly one approval',async t=>{
 const {f,c,selection}=await setup(t),r=await Promise.all([confirmChallenge(f,c.challengeId,selection,yes),confirmChallenge(f,c.challengeId,selection,yes)]);assert.equal(n(f),1);assert.ok(r.every(x=>x.read.message.status==='SYNTHETIC_APPROVAL_RECONSTRUCTED'));assert.equal(inspect(f.path,d=>d.prepare('SELECT state FROM fixture_challenges').get().state),'CONSUMED');trace('I04',r);
});
test('I05 foreign actor context cannot enter fixture provisioning',async t=>{
 const {f,c,selection}=await setup(t),before=state(f.path);await assert.rejects(()=>fixtureCall('confirm',f.path,{...f.context,owner:'other'},f.request,{challengeId:c.challengeId,selection,choices:yes}),/SYNTHETIC_FIXTURE_ONLY/);assert.equal(state(f.path),before);
});
test('I06 changed exact request cannot consume original challenge',async t=>{
 const {f,c,selection}=await setup(t),r=await confirmChallenge({...f,request:{...f.request,title:'other'}},c.challengeId,selection,yes);assert.equal(r.writer.message.code,'CHALLENGE_BINDING_MISMATCH');assert.equal(n(f),0);
});
test('I07 expired challenge rejects confirmation without approval',async t=>{
 const {f,c,selection}=await setup(t);mutate(f.path,d=>d.exec('UPDATE fixture_challenges SET expires_at=0'));const r=await confirmChallenge(f,c.challengeId,selection,yes);assert.equal(r.writer.message.code,'CHALLENGE_EXPIRED');assert.equal(n(f),0);
});
test('I08 revoked write grant rejects confirmation',async t=>{
 const {f,c,selection}=await setup(t);await revoke(f.path,f.context,f.request.grantId);const r=await confirmChallenge(f,c.challengeId,selection,yes);assert.equal(r.writer.message.code,'GRANT_INACTIVE');assert.equal(n(f),0);
});
test('I09 changed generation rejects stale confirmation',async t=>{
 const {f,c,selection}=await setup(t);mutate(f.path,d=>d.exec('UPDATE grants SET generation=2'));const r=await confirmChallenge(f,c.challengeId,selection,yes);assert.equal(r.writer.message.code,'GRANT_SCOPE');assert.equal(n(f),0);
});
test('I10 missing late-completion acknowledgement cannot issue fixture approval',async t=>{
 const {f,c,selection}=await setup(t),r=await confirmChallenge(f,c.challengeId,selection,{...yes,allowLateCompletion:false});assert.equal(r.writer.message.code,'EXPLICIT_OWNER_CONFIRMATION_REQUIRED');assert.equal(n(f),0);
});
test('I11 early client time cannot override expired server grant',async t=>{
 const {f,c,selection}=await setup(t);mutate(f.path,d=>d.exec('UPDATE grants SET expires_at=0'));selection.selectedAt=0;const r=await confirmChallenge(f,c.challengeId,selection,yes);assert.equal(r.writer.message.code,'SERVER_DEADLINE_EXPIRED');assert.equal(n(f),0);
});
test('I12 false precommit ACK cannot substitute for readback',async t=>{
 const {f,c,selection}=await setup(t),r=await confirmChallenge(f,c.challengeId,selection,yes,{phase:'falseAck'});assert.equal(r.writer.message.fakeAck,true);assert.equal(r.read.message.status,'NO_APPROVAL');assert.equal(n(f),0);trace('I12',r);
});
test('I13 replay after runtime consumption cannot reactivate approval',async t=>{
 const {f,c,selection}=await setup(t);await confirmChallenge(f,c.challengeId,selection,yes);await execute(f.path,f.context,f.request,{readCapability:f.readCapability});const before=state(f.path),r=await confirmChallenge(f,c.challengeId,selection,yes);assert.equal(r.read.message.consumed,1);assert.equal(n(f),1);assert.equal(state(f.path),before);trace('I13',r);
});
test('I14 incomplete consumed challenge gives unknown without silent repair',async t=>{
 const {f,c,selection}=await setup(t);await confirmChallenge(f,c.challengeId,selection,yes);mutate(f.path,d=>d.exec('DELETE FROM approvals'));const before=state(f.path),r=await inspectApproval(f,c.challengeId);assert.equal(r.message.status,'UNKNOWN');assert.equal(r.message.code,'APPROVAL_BINDING_MISMATCH');assert.equal(state(f.path),before);assert.equal(n(f),0);trace('I14',r);
});

const nativeEnvironment=f=>({LD_PRELOAD:process.env.VD_NATIVE_LIBRARY,VD_WAL_PATH:f.path+'-wal',VD_WAL_ARM:join(f.dir,'approval-arm'),VD_NATIVE_TRACE:join(f.dir,'approval-native.jsonl')});
test('I15 real native SIGKILL inside approval COMMIT leaves neither consumption nor approval',async t=>{
 assert.ok(process.env.VD_NATIVE_LIBRARY);const {f,c,selection}=await setup(t),environment={...nativeEnvironment(f),VD_NATIVE_MODE:'kill-before-wal-write'},before=state(f.path),r=await confirmChallenge(f,c.challengeId,selection,yes,{environment});
 const native=JSON.parse(readFileSync(environment.VD_NATIVE_TRACE,'utf8').trim());assert.equal(native.kind,'NATIVE_COMMIT_INTERRUPT');assert.equal(r.writer.signal,'SIGKILL');assert.equal(r.read.message.status,'NO_APPROVAL');assert.equal(state(f.path),before);assert.equal(n(f),0);trace('I15',{r,native});
});
test('I16 late durable fixture approval is historical but expired and cannot execute an effect',async t=>{
 assert.ok(process.env.VD_NATIVE_LIBRARY);const {f,c,selection}=await setup(t,{lifetime:700}),environment=nativeEnvironment(f),r=await confirmChallenge(f,c.challengeId,selection,yes,{environment});
 const native=JSON.parse(readFileSync(environment.VD_NATIVE_TRACE,'utf8').trim());assert.ok(native.startMs<f.expiry&&f.expiry<native.endMs);assert.equal(r.read.message.status,'SYNTHETIC_APPROVAL_RECONSTRUCTED');assert.equal(r.read.message.expired,true);assert.equal(n(f),1);
 const result=await execute(f.path,f.context,f.request,{readCapability:f.readCapability});assert.equal(result.status,'DENIED');assert.equal(result.code,'VALIDATION_DEADLINE_EXPIRED');assert.equal(inspect(f.path,d=>d.prepare('SELECT count(*) n FROM events').get().n),0);trace('I16',{r,native,result});
});
