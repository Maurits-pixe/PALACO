import test from 'node:test';
import assert from 'node:assert/strict';
import {checkAdmissionSnapshot} from '../src/admission.mjs';
import {prepareConsent,recordConsentSelection} from '../src/client.mjs';
import {digest,PROFILE} from '../src/value.mjs';
import {fixture,state} from './fixture.mjs';
function setup(t) {
 const f=fixture(t),now=Date.now(),preview=prepareConsent(f.context,f.request,{grantExpiresAt:f.expiry,approvalExpiresAt:f.approvalExpiry});
 const selection=recordConsentSelection(preview,{approveExactRequest:true,allowLateCompletion:true},now);
 const snapshot={kind:'SYNTHETIC_ADMISSION_SNAPSHOT_V1',now,timeTrusted:true,originVerified:true,actor:{...f.context,verified:true},calendar:{id:f.request.calendarId,owner:f.context.owner,tenant:f.context.tenant,writeAcl:true},profileAllowed:true,grant:{id:f.request.grantId,calendarId:f.request.calendarId,...f.context,generation:1,action:'CREATE_OWN_EVENT',state:'ACTIVE',expiresAt:f.expiry,contractProfile:PROFILE,finishAfterExpiry:true},approvalExpiresAt:f.approvalExpiry,challenge:{id:'synthetic-challenge',state:'OPEN',expiresAt:f.expiry,contextDigest:digest(f.context),requestDigest:digest(f.request),previewDigest:preview.previewDigest},confirmedChallengeId:'synthetic-challenge',confirmedPreviewDigest:preview.previewDigest,confirmedChoices:{approveExactRequest:true,allowLateCompletion:true}};
 return {f,snapshot,selection};
}
test('A01 complete synthetic snapshot satisfies requirements but grants no authority or writes',t=>{
 const {f,snapshot,selection}=setup(t),before=state(f.path);const result=checkAdmissionSnapshot(snapshot,f.context,f.request,selection);assert.equal(result.status,'SNAPSHOT_REQUIREMENTS_SATISFIED');assert.equal(result.authorityGranted,false);assert.equal(result.approval,undefined);assert.equal(state(f.path),before);
});
for(const [id,edit,code] of [
 ['A02',x=>{delete x.snapshot.actor.verified;},'OWNER_AUTH_UNVERIFIED'],
 ['A03',x=>{x.snapshot.originVerified=false;},'OWNER_AUTH_UNVERIFIED'],
 ['A04',x=>{x.snapshot.actor.owner='other';},'ACTOR_CONTEXT_MISMATCH'],
 ['A05',x=>{x.snapshot.actor.tenant='other';},'ACTOR_CONTEXT_MISMATCH'],
 ['A06',x=>{x.snapshot.actor.session='other';},'ACTOR_CONTEXT_MISMATCH'],
 ['A07',x=>{x.snapshot.grant.generation=2;},'GRANT_SCOPE'],
 ['A08',x=>{x.snapshot.grant.state='REVOKED';},'GRANT_INACTIVE'],
 ['A09',x=>{x.snapshot.now=x.snapshot.grant.expiresAt;x.selection.selectedAt=0;},'SERVER_DEADLINE_EXPIRED'],
 ['A10',x=>{x.snapshot.challenge.state='CONSUMED';},'CHALLENGE_NOT_OPEN'],
 ['A11',x=>{x.snapshot.challenge.expiresAt=x.snapshot.now;},'CHALLENGE_EXPIRED'],
 ['A12',x=>{x.snapshot.profileAllowed=false;},'POLICY_DENIED'],
 ['A13',x=>{x.snapshot.confirmedChoices.allowLateCompletion=false;},'EXPLICIT_OWNER_CONFIRMATION_REQUIRED'],
 ['A14',x=>{x.snapshot.confirmedChallengeId='other';},'EXPLICIT_OWNER_CONFIRMATION_REQUIRED'],
 ['A15',x=>{x.snapshot.challenge.requestDigest='wrong';},'CHALLENGE_BINDING_MISMATCH'],
 ['A16',x=>{x.selection.previewDigest='wrong';},'SELECTION_BINDING_MISMATCH'],
 ['A17',x=>{x.snapshot.timeTrusted=false;},'TIME_UNVERIFIED'],
 ['A18',x=>{x.snapshot.calendar.writeAcl=false;},'CALENDAR_SCOPE'],
 ['A19',x=>{x.snapshot.grant.finishAfterExpiry=false;},'PROFILE_OPT_IN_REQUIRED'],
 ['A20',x=>{x.snapshot.approvalExpiresAt=x.snapshot.now;},'SERVER_DEADLINE_EXPIRED'],
])test(id+' rejects '+code+' without side effects',t=>{
 const input=setup(t),before=state(input.f.path);edit(input);const r=checkAdmissionSnapshot(input.snapshot,input.f.context,input.f.request,input.selection);assert.equal(r.status,'REJECTED');assert.equal(r.code,code);assert.equal(r.authorityGranted,false);assert.equal(state(input.f.path),before);
});
