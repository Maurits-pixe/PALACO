// Explicit synthetic fixture authority; never imported by src/index.mjs.
import {DatabaseSync} from 'node:sqlite';
import {randomUUID} from 'node:crypto';
import {writeFileSync} from 'node:fs';
import {canonical,digest,validate,PROFILE} from '../src/value.mjs';
import {prepareConsent} from '../src/client.mjs';
import {checkAdmissionSnapshot} from '../src/admission.mjs';
const tell=data=>new Promise((resolve,reject)=>process.send(data,error=>error?reject(error):resolve()));
const kill=()=>process.kill(process.pid,'SIGKILL');
process.once('message',async input=>{
 let db;
 try {
  const {mode,path,context,request}=input;validate(context,request);
  db=new DatabaseSync(path,{readOnly:mode==='read',timeout:5000});
  if(mode==='prepare')db.exec("CREATE TABLE IF NOT EXISTS fixture_challenges(id TEXT PRIMARY KEY, operation_id TEXT UNIQUE NOT NULL, request_digest TEXT NOT NULL, context_digest TEXT NOT NULL, preview_digest TEXT NOT NULL, expires_at INTEGER NOT NULL, approval_expires_at INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('OPEN','CONSUMED')), approval_id TEXT UNIQUE NOT NULL)");
  if(mode==='read') {
   db.exec('PRAGMA query_only=ON; BEGIN');
   const c=db.prepare('SELECT * FROM fixture_challenges WHERE id=?').get(input.challengeId),ap=db.prepare('SELECT * FROM approvals WHERE id=?').get(request.approvalId);
   if(!c||c.operation_id!==request.operationId||c.request_digest!==digest(request)||c.context_digest!==digest(context)){db.exec('ROLLBACK');await tell({status:'UNKNOWN',code:'CHALLENGE_BINDING_MISMATCH'});return;}
   if(c.state==='OPEN'&&!ap){db.exec('ROLLBACK');await tell({status:'NO_APPROVAL',challengeId:c.id});return;}
   if(c.state!=='CONSUMED'||!ap||ap.id!==c.approval_id||ap.grant_id!==request.grantId||ap.request_digest!==c.request_digest||ap.context_digest!==c.context_digest||ap.expires_at!==c.approval_expires_at||ap.contract_profile!==PROFILE||ap.finish_after_expiry!==1){db.exec('ROLLBACK');await tell({status:'UNKNOWN',code:'APPROVAL_BINDING_MISMATCH'});return;}
   db.exec('COMMIT');await tell({status:'SYNTHETIC_APPROVAL_RECONSTRUCTED',challengeId:c.id,approvalId:ap.id,consumed:ap.consumed,expired:Date.now()>=ap.expires_at,realAuthorityGranted:false});return;
  }
  db.exec('PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL; BEGIN IMMEDIATE');
  const g=db.prepare('SELECT * FROM grants WHERE id=?').get(request.grantId),cal=db.prepare('SELECT * FROM calendars WHERE id=?').get(request.calendarId);
  if(!g||!cal)throw Error('FIXTURE_SCOPE');
  if(mode==='prepare') {
   if(!Number.isSafeInteger(input.challengeExpiry)||!Number.isSafeInteger(input.approvalExpiry))throw Error('INVALID_EXPIRY');
   const preview=prepareConsent(context,request,{grantExpiresAt:g.expires_at,approvalExpiresAt:input.approvalExpiry});
   const existing=db.prepare('SELECT * FROM fixture_challenges WHERE operation_id=?').get(request.operationId);
   if(existing){if(existing.request_digest!==digest(request)||existing.context_digest!==digest(context)||existing.preview_digest!==preview.previewDigest)throw Error('CHALLENGE_BINDING_MISMATCH');db.exec('ROLLBACK');await tell({status:'SYNTHETIC_CHALLENGE',challengeId:existing.id,preview});return;}
   const id=randomUUID();db.prepare("INSERT INTO fixture_challenges VALUES (?,?,?,?,?,?,?,'OPEN',?)").run(id,request.operationId,digest(request),digest(context),preview.previewDigest,Math.min(input.challengeExpiry,g.expires_at,input.approvalExpiry),input.approvalExpiry,request.approvalId);
   db.exec('COMMIT');await tell({status:'SYNTHETIC_CHALLENGE',challengeId:id,preview});return;
  }
  if(mode!=='confirm')throw Error('INVALID_MODE');
  const c=db.prepare('SELECT * FROM fixture_challenges WHERE id=?').get(input.challengeId);
  if(!c||c.operation_id!==request.operationId||c.request_digest!==digest(request)||c.context_digest!==digest(context))throw Error('CHALLENGE_BINDING_MISMATCH');
  if(c.state==='CONSUMED'){db.exec('ROLLBACK');await tell({status:'RECONSTRUCT_EXISTING'});return;}
  // All identity/origin/time assertions below are fixture provisioning, not authentication.
  const snapshot={kind:'SYNTHETIC_ADMISSION_SNAPSHOT_V1',now:Date.now(),timeTrusted:true,originVerified:true,actor:{...context,verified:true},calendar:{id:cal.id,owner:cal.owner,tenant:cal.tenant,writeAcl:cal.write_acl===1},profileAllowed:true,grant:{id:g.id,calendarId:g.calendar_id,owner:g.owner,tenant:g.tenant,session:g.session,generation:g.generation,action:g.action,state:g.state,expiresAt:g.expires_at,contractProfile:g.contract_profile,finishAfterExpiry:g.finish_after_expiry===1},approvalExpiresAt:c.approval_expires_at,challenge:{id:c.id,state:c.state,expiresAt:c.expires_at,contextDigest:c.context_digest,requestDigest:c.request_digest,previewDigest:c.preview_digest},confirmedChallengeId:input.challengeId,confirmedPreviewDigest:input.selection?.previewDigest,confirmedChoices:input.choices};
  const checked=checkAdmissionSnapshot(snapshot,context,request,input.selection);if(checked.status!=='SNAPSHOT_REQUIREMENTS_SATISFIED')throw Error(checked.code);
  db.prepare('INSERT INTO approvals VALUES (?,?,?,?,?,0,?,1)').run(request.approvalId,request.grantId,digest(request),digest(context),c.approval_expires_at,PROFILE);
  const changed=db.prepare("UPDATE fixture_challenges SET state='CONSUMED' WHERE id=? AND state='OPEN'").run(c.id);if(changed.changes!==1)throw Error('CHALLENGE_CONFLICT');
  await tell({status:'FIXTURE_WRITE_ATTEMPT'});
  if(input.phase==='beforeCommit')kill();
  if(input.phase==='falseAck'){await tell({status:'SYNTHETIC_APPROVAL_RECONSTRUCTED',fakeAck:true});kill();}
  if(process.env.VD_WAL_ARM)writeFileSync(process.env.VD_WAL_ARM,'armed');
  db.exec('COMMIT');kill();
 }catch(error){if(db?.isTransaction)db.exec('ROLLBACK');await tell({status:input.mode==='read'?'UNKNOWN':'REJECTED',code:error.message});}
 finally{if(db)db.close();process.disconnect();}
});
