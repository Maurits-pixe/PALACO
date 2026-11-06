import {DatabaseSync} from 'node:sqlite';
import {writeFileSync} from 'node:fs';
import {canonical,digest,validate,exact,CONTEXT_KEYS,PROFILE,RECEIPT_VERSION,withinValidationWindow} from './value.mjs';
const kill=()=>process.kill(process.pid,'SIGKILL');
const tell=x=>new Promise((resolve,reject)=>process.send(x,error=>error?reject(error):resolve()));
process.once('message',async input=>{
 let db;
 try {
  const {mode,databasePath,context,request,grantId}=input;
  const anchor=BigInt(input.timeAnchorMono);let high=input.timeFloor;
  const now=()=>high=Math.max(high,Date.now(),input.timeFloor+Number((process.hrtime.bigint()-anchor+999999n)/1000000n));
  db=new DatabaseSync(databasePath,{readOnly:mode==='read',timeout:5000,allowExtension:false});
  if(db.prepare('PRAGMA user_version').get().user_version!==101||db.prepare('PRAGMA journal_mode').get().journal_mode!=='wal')throw Error('SCHEMA_OR_MODE_MISMATCH');
  if(mode==='read') {
   validate(context,request);db.exec('PRAGMA query_only=ON; BEGIN');
   const d=db.prepare('SELECT * FROM decisions WHERE operation_id=?').get(request.operationId);
   if(!d){db.exec('ROLLBACK');await tell({status:'RESULT_UNKNOWN',code:'NO_DURABLE_COMMIT'});return;}
   const b=JSON.parse(d.binding),rd=digest(request),cd=digest(context);
   const e=db.prepare('SELECT * FROM events WHERE id=?').get(request.eventId);
   const v=db.prepare('SELECT * FROM versions WHERE event_id=?').get(request.eventId);
   const r=db.prepare('SELECT * FROM receipts WHERE operation_id=?').get(request.operationId);
   const a=db.prepare('SELECT * FROM audit WHERE seq=?').get(d.audit_seq);
   const g=db.prepare('SELECT * FROM grants WHERE id=?').get(request.grantId);
   const ap=db.prepare('SELECT * FROM approvals WHERE id=?').get(request.approvalId);
   const cal=db.prepare('SELECT * FROM calendars WHERE id=?').get(request.calendarId);
   const expected={contractProfile:PROFILE,receiptVersion:RECEIPT_VERSION,finishAfterExpiry:true,operationId:request.operationId,requestDigest:rd,contextDigest:cd,calendarId:request.calendarId,eventId:request.eventId,grantId:request.grantId,generation:request.generation,approvalId:request.approvalId,snapshotDigest:digest({id:request.eventId,calendarId:request.calendarId,revision:1,title:request.title}),grantExpiresAt:g?.expires_at??0,approvalExpiresAt:ap?.expires_at??0,validatedAt:d.validated_at,validationMeasurement:'PRECOMMIT_VALIDATION_OBSERVATION',timeTrustProfile:'SYNTHETIC_LIVE_SUPERVISOR_MONOTONE_V1',auditSequence:d.audit_seq};
   const good=canonical(b)===canonical(expected)&&d.request_digest===rd&&d.context_digest===cd&&
    withinValidationWindow(b.validatedAt,b.grantExpiresAt,b.approvalExpiresAt)&&
    r?.binding===canonical(b)&&a?.binding===canonical(b)&&a?.kind==='DECISION'&&a?.operation_id===request.operationId&&a?.grant_id===request.grantId&&
    e?.calendar_id===request.calendarId&&e?.revision===1&&e?.title===request.title&&v?.revision===1&&v?.snapshot_digest===b.snapshotDigest&&
    g?.calendar_id===request.calendarId&&g?.owner===context.owner&&g?.tenant===context.tenant&&g?.session===context.session&&g?.generation===request.generation&&g?.action==='CREATE_OWN_EVENT'&&g?.contract_profile===PROFILE&&g?.finish_after_expiry===1&&
    ap?.grant_id===request.grantId&&ap?.request_digest===rd&&ap?.context_digest===cd&&ap?.consumed===1&&ap?.contract_profile===PROFILE&&ap?.finish_after_expiry===1&&
    cal?.owner===context.owner&&cal?.tenant===context.tenant;
   if(!good){db.exec('ROLLBACK');await tell({status:'RESULT_UNKNOWN',code:'BINDING_MISMATCH'});return;}
   db.exec('COMMIT');
   const withheld=code=>tell({status:'COMMITTED_RESULT_WITHHELD',code,contractProfile:PROFILE,operationId:b.operationId,auditSequence:b.auditSequence});
   if(input.expectedValidationAt!==b.validatedAt){await withheld('TIME_TRUST_UNAVAILABLE');return;}
   const permit=()=>{
    const fresh=db.prepare('SELECT state,generation FROM grants WHERE id=?').get(request.grantId);
    if(fresh.state!=='ACTIVE'||fresh.generation!==request.generation)return 'WRITE_REVOKED';
    const currentCal=db.prepare('SELECT * FROM calendars WHERE id=?').get(request.calendarId);
    if(!currentCal||currentCal.owner!==context.owner||currentCal.tenant!==context.tenant||currentCal.write_acl!==1)return 'CALENDAR_SCOPE';
    const cap=input.readCapability;
    if(!cap||Object.keys(cap).sort().join()!=='generation,grantId')return 'READ_AUTHORITY_REQUIRED';
    const read=db.prepare('SELECT * FROM read_grants WHERE id=?').get(cap.grantId);
    if(!read||read.state!=='ACTIVE'||read.generation!==cap.generation||read.owner!==context.owner||read.tenant!==context.tenant||read.session!==context.session||read.calendar_id!==request.calendarId||read.action!=='READ_OWN_EVENT'||now()>=read.expires_at)return 'READ_AUTHORITY_REQUIRED';
    return null;
   };
   let denied=permit();if(denied){await withheld(denied);return;}
   if(process.env.VD_READ_READY){writeFileSync(process.env.VD_READ_READY,'ready');await new Promise(r=>setTimeout(r,300));}
   // Observe reconstruction time before the final authority check, so a forward
   // clock observation cannot invalidate read expiry after the last check.
   const durableObservedAt=now();
   denied=permit();if(denied){await withheld(denied);return;}
   await tell({status:'COMMITTED',releasePoint:'LOCKED_WORKER_IPC_SEND',receipt:{...b,durability:'RECONSTRUCTED_COMMIT',durableObservedAt,durabilityMeasurement:'READBACK_UPPER_BOUND',exactDurableAt:'UNKNOWN',observedAfterExpiry:durableObservedAt>=Math.min(b.grantExpiresAt,b.approvalExpiresAt),deadlineSatisfied:'VALIDATION_DEADLINE_ONLY'},event:{...e}});return;
  }
  db.exec('PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL; BEGIN IMMEDIATE');
  if(mode==='revoke'||mode==='revokeRead') {
   exact(context,CONTEXT_KEYS);const table=mode==='revoke'?'grants':'read_grants';
   const g=db.prepare('SELECT * FROM '+table+' WHERE id=?').get(grantId);
   if(!g||g.owner!==context.owner||g.tenant!==context.tenant||g.session!==context.session)throw Error('SOURCE_SCOPE');
   if(g.state==='ACTIVE'){
    db.prepare('INSERT INTO audit(kind,grant_id,binding) VALUES (?,?,?)').run(mode==='revoke'?'REVOKE':'READ_REVOKE',grantId,canonical({grantId,generation:g.generation}));
    db.prepare("UPDATE "+table+" SET state='REVOKED' WHERE id=?").run(grantId);
   }
   db.exec('COMMIT');kill();return;
  }
  if(mode!=='write')throw Error('INVALID_MODE');validate(context,request);
  if(db.prepare('SELECT 1 FROM decisions WHERE operation_id=?').get(request.operationId)){db.exec('ROLLBACK');await tell({status:'RECONSTRUCTION_REQUIRED'});kill();return;}
  const cal=db.prepare('SELECT * FROM calendars WHERE id=?').get(request.calendarId);
  const g=db.prepare('SELECT * FROM grants WHERE id=?').get(request.grantId);
  const ap=db.prepare('SELECT * FROM approvals WHERE id=?').get(request.approvalId);
  const rd=digest(request),cd=digest(context);
  if(!cal||cal.owner!==context.owner||cal.tenant!==context.tenant||cal.write_acl!==1||!g||g.calendar_id!==cal.id||g.owner!==context.owner||g.tenant!==context.tenant||g.session!==context.session||g.generation!==request.generation||g.action!=='CREATE_OWN_EVENT')throw Error('SOURCE_SCOPE');
  if(g.state!=='ACTIVE')throw Error('CONSENT_INACTIVE');
  if(g.contract_profile!==PROFILE||g.finish_after_expiry!==1||!ap||ap.contract_profile!==PROFILE||ap.finish_after_expiry!==1)throw Error('PROFILE_OPT_IN_REQUIRED');
  if(ap.grant_id!==g.id||ap.request_digest!==rd||ap.context_digest!==cd||ap.consumed!==0)throw Error('APPROVAL_REQUIRED');
  const seq=Number(db.prepare("INSERT INTO audit(kind,operation_id,grant_id,binding) VALUES ('DECISION',?,?,?)").run(request.operationId,g.id,'{}').lastInsertRowid);
  const snapshotDigest=digest({id:request.eventId,calendarId:cal.id,revision:1,title:request.title});
  db.prepare('INSERT INTO events VALUES (?,?,1,?)').run(request.eventId,cal.id,request.title);
  db.prepare('INSERT INTO versions VALUES (?,1,?)').run(request.eventId,snapshotDigest);
  db.prepare('UPDATE approvals SET consumed=1 WHERE id=? AND consumed=0').run(ap.id);
  const validatedAt=now();
  if(!withinValidationWindow(validatedAt,g.expires_at,ap.expires_at))throw Error('VALIDATION_DEADLINE_EXPIRED');
  const b={contractProfile:PROFILE,receiptVersion:RECEIPT_VERSION,finishAfterExpiry:true,operationId:request.operationId,requestDigest:rd,contextDigest:cd,calendarId:cal.id,eventId:request.eventId,grantId:g.id,generation:g.generation,approvalId:ap.id,snapshotDigest,grantExpiresAt:g.expires_at,approvalExpiresAt:ap.expires_at,validatedAt,validationMeasurement:'PRECOMMIT_VALIDATION_OBSERVATION',timeTrustProfile:'SYNTHETIC_LIVE_SUPERVISOR_MONOTONE_V1',auditSequence:seq};
  const binding=canonical(b);
  db.prepare('UPDATE audit SET binding=? WHERE seq=?').run(binding,seq);
  db.prepare('INSERT INTO decisions VALUES (?,?,?,?,?,?)').run(request.operationId,seq,rd,cd,binding,validatedAt);
  db.prepare('INSERT INTO receipts VALUES (?,?)').run(request.operationId,binding);
  await tell({status:'WRITE_ATTEMPT',created:true,validatedAt});
  if(process.env.VD_TEST_PHASE==='beforeCommit')kill();
  if(process.env.VD_TEST_PHASE==='fakeAckBeforeCommit'){await tell({status:'COMMITTED',created:true,validatedAt,fakeAck:true});kill();}
  if(process.env.VD_WRITE_READY)writeFileSync(process.env.VD_WRITE_READY,'ready');
  if(process.env.VD_WAL_ARM)writeFileSync(process.env.VD_WAL_ARM,'armed');
  db.exec('COMMIT');
  if(process.env.VD_TEST_PHASE==='errorAfterCommit')await tell({status:'DENIED',code:'SYNTHETIC_POST_COMMIT_ERROR'});
  kill();
 }catch(error){if(db?.isTransaction)db.exec('ROLLBACK');await tell({status:input.mode==='read'?'RESULT_UNKNOWN':'DENIED',code:error.message});}
 finally{if(db)db.close();process.disconnect();}
});
