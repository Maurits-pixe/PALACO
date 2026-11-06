import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareServiceTask} from '../src/index.mjs';
import {prepareConsent} from '../../hannie-validation-deadline/src/client.mjs';
const consumer=()=>({purpose:'CONSUMER',context:{owner:'example-owner',tenant:'example-tenant',session:'example-session'},request:{contractProfile:'HARA_WRITE_VALIDATION_DEADLINE_DRAFT_1',finishAfterExpiry:true,operationId:'op',calendarId:'calendar',eventId:'event',grantId:'grant',generation:1,approvalId:'approval',title:'Voorbeeldafspraak'},deadlines:{grantExpiresAt:2000,approvalExpiresAt:1500}});
const maintenance=()=>({purpose:'MAINTENANCE',repository:'example/project',sourceCommit:'a'.repeat(40),changeSummary:'Beschrijf de voorgestelde wijziging',verificationPlan:['Controleer de concrete wijziging']});
test('S01 consumer proposal reuses exact Hannie disclosure, without execution authority',()=>{
 const t=consumer(),r=prepareServiceTask(t);assert.deepEqual(r.proposal.preview,prepareConsent(t.context,t.request,t.deadlines));
 assert.equal(r.status,'DRAFT_REQUIRES_HOST_VERIFICATION');assert.equal(r.canExecute,false);assert.equal(r.authorityGranted,false);assert.equal(r.hostBinding,'UNRESOLVED');
});
test('S02 maintenance binds a pinned source and remains a proposal',()=>{
 const r=prepareServiceTask(maintenance());assert.equal(r.proposal.action,'PREPARE_MAINTENANCE_CHANGE');assert.equal(r.proposal.sourceCommit,'a'.repeat(40));assert.equal(r.canExecute,false);assert.equal(r.requestedRoute,'PALACO ONE');
});
test('S03 purpose substitution and cross-purpose fields are rejected',()=>{
 for(const t of [{...consumer(),purpose:'MAINTENANCE'},{...maintenance(),purpose:'CONSUMER'},{...consumer(),repository:'example/project'},{...maintenance(),context:consumer().context}])assert.throws(()=>prepareServiceTask(t));
});
test('S04 caller cannot inject a grant, trusted time, status or dispatch command',()=>{
 for(const field of ['authorityGranted','timeTrusted','status','command','trustedHarnessEnvironment','databasePath'])for(const t of [consumer(),maintenance()])assert.throws(()=>prepareServiceTask({...t,[field]:true}));
});
test('S05 caller mutation and output mutation cannot alter prepared binding',()=>{
 const t=consumer(),r=prepareServiceTask(t),digest=r.proposalDigest;t.request.title='Changed';assert.equal(r.proposal.preview.title,'Voorbeeldafspraak');assert.throws(()=>{r.proposal.preview.request.title='Changed';},TypeError);assert.equal(r.proposalDigest,digest);
 const m=maintenance(),p=prepareServiceTask(m);m.verificationPlan.push('Later');assert.equal(p.proposal.verificationPlan.length,1);assert.throws(()=>p.proposal.verificationPlan.push('Changed'),TypeError);
});
test('S06 key order does not change binding; source, scope, deadlines and content changes do',()=>{
 for(const t of [consumer(),maintenance()]){const reordered=Object.fromEntries(Object.entries(t).reverse());assert.equal(prepareServiceTask(t).proposalDigest,prepareServiceTask(reordered).proposalDigest);}
 for(const mutate of [t=>t.context.owner='other',t=>t.context.tenant='other',t=>t.context.session='other',t=>t.request.calendarId='other',t=>t.request.title='other',t=>t.deadlines.approvalExpiresAt++]){const t=consumer(),before=prepareServiceTask(t).proposalDigest;mutate(t);assert.notEqual(prepareServiceTask(t).proposalDigest,before);}
 for(const mutate of [t=>t.sourceCommit='b'.repeat(40),t=>t.repository='example/other',t=>t.verificationPlan.push('Another check')]){const t=maintenance(),before=prepareServiceTask(t).proposalDigest;mutate(t);assert.notEqual(prepareServiceTask(t).proposalDigest,before);}
});
test('S07 maintenance requires an exact commit and nonempty bounded verification plan',()=>{
 for(const sourceCommit of ['main','a'.repeat(39),null])assert.throws(()=>prepareServiceTask({...maintenance(),sourceCommit}));
 for(const verificationPlan of [[],[''],Array(13).fill('check'),['line\nbreak']])assert.throws(()=>prepareServiceTask({...maintenance(),verificationPlan}));
});
test('S08 unsupported profile and absent late-completion opt-in cannot become consumer proposals',()=>{
 for(const edit of [t=>t.request.contractProfile='legacy',t=>t.request.finishAfterExpiry=false]){const t=consumer();edit(t);assert.throws(()=>prepareServiceTask(t));}
});
test('S09 malformed data, cycles and accessors are rejected without evaluating getters',()=>{
 for(const t of [null,[],new Date(),{purpose:'UNKNOWN'}])assert.throws(()=>prepareServiceTask(t));
 const t=maintenance();t.verificationPlan.push(t);assert.throws(()=>prepareServiceTask(t));
 let reads=0;const getter=maintenance();Object.defineProperty(getter,'changeSummary',{enumerable:true,get(){reads++;return 'x';}});assert.throws(()=>prepareServiceTask(getter));assert.equal(reads,0);
});
test('S10 no current-time or source-verification claim is inferred from successful preparation',()=>{
 const t=consumer();t.deadlines={grantExpiresAt:1,approvalExpiresAt:1};const r=prepareServiceTask(t);assert.equal(r.canExecute,false);assert.equal(r.authorityGranted,false);assert.equal(r.validatedAt,undefined);assert.equal(r.approval,undefined);
 const m=prepareServiceTask(maintenance());assert.equal(m.sourceVerified,undefined);assert.equal(m.receipt,undefined);
});
