import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareConsent,recordConsentSelection,presentResult} from '../src/client.mjs';
import {digest} from '../src/value.mjs';
import {fixture} from './fixture.mjs';
import {execute} from '../src/index.mjs';
const clone=x=>JSON.parse(JSON.stringify(x));
const preview=f=>prepareConsent(f.context,f.request,{grantExpiresAt:f.expiry,approvalExpiresAt:f.approvalExpiry});
const selected={approveExactRequest:true,allowLateCompletion:true};

test('C01 consent presents exact command and unbounded late-completion risk',t=>{
 const f=fixture(t),p=preview(f);assert.equal(p.title,f.request.title);assert.ok(p.riskText.includes('geen gegarandeerde maximale vertraging'));assert.deepEqual(p.requiredChoices,['approveExactRequest','allowLateCompletion']);assert.equal(p.request.finishAfterExpiry,true);
});
test('C02 both explicit selections required; none creates owner authority',t=>{
 const f=fixture(t),p=preview(f);
 for(const choice of [{approveExactRequest:true,allowLateCompletion:false},{approveExactRequest:false,allowLateCompletion:true}])assert.throws(()=>recordConsentSelection(p,choice,Date.now()),/EXPLICIT_SELECTION_REQUIRED/);
 const r=recordConsentSelection(p,selected,Date.now());assert.equal(r.kind,'UNAUTHENTICATED_CONSENT_SELECTION');assert.equal(r.status,'REQUIRES_OWNER_AUTHENTICATION');assert.equal(r.requestDigest,digest(f.request));assert.equal(r.grant,undefined);
});
test('C03 mutated preview or omitted risk disclosure cannot be confirmed',t=>{
 const f=fixture(t),p=preview(f);for(const edit of [x=>{x.title='different';},x=>{x.riskText='';},x=>{x.request.title='different';}]){const copy=clone(p);edit(copy);assert.throws(()=>recordConsentSelection(copy,selected,Date.now()),/CONSENT_PREVIEW_CHANGED/);}
});
test('C04 preview does not retain mutable caller request and expires at equality',t=>{
 const f=fixture(t),p=preview(f),original=f.request.title;f.request.title='later caller edit';assert.equal(p.request.title,original);assert.throws(()=>recordConsentSelection(p,selected,Math.min(f.expiry,f.approvalExpiry)),/CONSENT_SELECTION_EXPIRED/);
});
test('C05 unknown and withheld outcomes never expose contents or invite automatic retry',t=>{
 const f=fixture(t),unknown=presentResult({status:'RESULT_UNKNOWN'},f.context,f.request);assert.equal(unknown.state,'UNKNOWN');assert.equal(unknown.canAutomaticallyRetry,false);assert.equal(unknown.title,undefined);
 const held=presentResult({status:'COMMITTED_RESULT_WITHHELD',contractProfile:f.request.contractProfile,operationId:f.request.operationId,auditSequence:1},f.context,f.request);assert.equal(held.state,'WITHHELD');assert.equal(held.title,undefined);
 assert.throws(()=>presentResult({status:'RESULT_UNKNOWN',event:{title:'leak'}},f.context,f.request),/UNEXPECTED_PAYLOAD/);
});
test('C06 client decodes an actual new-worker receipt without claiming timely durability',async t=>{
 const f=fixture(t),r=await execute(f.path,f.context,f.request,{readCapability:f.readCapability}),view=presentResult(r,f.context,f.request);assert.equal(view.state,'CONFIRMED');assert.equal(view.title,f.request.title);assert.equal(view.canAutomaticallyRetry,false);assert.ok(view.explanation.includes('opslag kon later'));
});
test('C07 unknown profile/version and old success statuses are rejected',async t=>{
 const f=fixture(t),r=await execute(f.path,f.context,f.request,{readCapability:f.readCapability});
 for(const edit of [x=>{x.receipt.contractProfile='legacy';},x=>{x.receipt.receiptVersion=2;}]){const copy=clone(r);edit(copy);assert.throws(()=>presentResult(copy,f.context,f.request),/UNSUPPORTED_RECEIPT_PROFILE/);}
 assert.throws(()=>presentResult({status:'SUCCEEDED'},f.context,f.request),/UNSUPPORTED_RESULT_STATUS/);
});
test('C08 wrong owner/session, request digest or event contents cannot be displayed',async t=>{
 const f=fixture(t),r=await execute(f.path,f.context,f.request,{readCapability:f.readCapability});
 assert.throws(()=>presentResult(r,{...f.context,session:'other'},f.request),/RECEIPT_BINDING_MISMATCH/);
 for(const edit of [x=>{x.receipt.requestDigest='0'.repeat(64);},x=>{x.event.title='different';}]){const copy=clone(r);edit(copy);assert.throws(()=>presentResult(copy,f.context,f.request),/BINDING_MISMATCH/);}
});
test('C09 late readback is distinguished from exact late commit, never converted to old receipt fields',async t=>{
 const f=fixture(t),r=await execute(f.path,f.context,f.request,{readCapability:f.readCapability});
 r.receipt.durableObservedAt=Math.max(r.receipt.validatedAt,r.receipt.grantExpiresAt,r.receipt.approvalExpiresAt)+1;r.receipt.observedAfterExpiry=true;
 const view=presentResult(r,f.context,f.request);assert.ok(view.timing.includes('na verlopen'));assert.equal(view.decisionAt,undefined);assert.equal(view.exactDurableAt,undefined);
 r.receipt.exactDurableAt=r.receipt.durableObservedAt;assert.throws(()=>presentResult(r,f.context,f.request),/UNSUPPORTED_TIME_SEMANTICS/);
});
test('C10 unexpected receipt fields or contradictory timing indicators fail closed',async t=>{
 const f=fixture(t),r=await execute(f.path,f.context,f.request,{readCapability:f.readCapability});const extra=clone(r);extra.receipt.decisionAt=123;assert.throws(()=>presentResult(extra,f.context,f.request),/INVALID_INPUT/);
 const mismatch=clone(r);mismatch.receipt.observedAfterExpiry=!mismatch.receipt.observedAfterExpiry;assert.throws(()=>presentResult(mismatch,f.context,f.request),/UNSUPPORTED_TIME_SEMANTICS/);
});

test('C11 denied outcomes stay separate from unknown commits and cannot carry payload',t=>{
 const f=fixture(t),view=presentResult({status:'DENIED',code:'VALIDATION_DEADLINE_EXPIRED'},f.context,f.request);assert.equal(view.state,'DENIED');assert.equal(view.canAutomaticallyRetry,false);assert.throws(()=>presentResult({status:'DENIED',receipt:{}},f.context,f.request),/UNEXPECTED_PAYLOAD/);
});
test('C12 missing historical trust never suggests that a fresh consent recreates it',t=>{
 const f=fixture(t),view=presentResult({status:'COMMITTED_RESULT_WITHHELD',code:'TIME_TRUST_UNAVAILABLE',contractProfile:f.request.contractProfile,operationId:f.request.operationId,auditSequence:1},f.context,f.request);assert.ok(view.explanation.includes('controle moet eerst'));assert.equal(view.explanation.includes('Nieuwe toestemming'),false);assert.equal(view.canAutomaticallyRetry,false);
});

test('C13 a withheld result requires a valid audit sequence before claiming a committed outcome',async t=>{
 const f=fixture(t),held=await execute(f.path,f.context,f.request);assert.equal(held.status,'COMMITTED_RESULT_WITHHELD');assert.equal(presentResult(held,f.context,f.request).state,'WITHHELD');
 for(const edit of [x=>{delete x.auditSequence;},x=>{x.auditSequence=0;},x=>{x.auditSequence='1';},x=>{x.auditSequence=1.5;}]){
  const malformed=clone(held);edit(malformed);assert.throws(()=>presentResult(malformed,f.context,f.request),/RESULT_BINDING_MISMATCH/);
 }
});
