import { DatabaseSync } from 'node:sqlite';
import { writeFileSync } from 'node:fs';
import { canonical, digest, validate, exact, CONTEXT_KEYS } from './value.mjs';
const kill = () => process.kill(process.pid, 'SIGKILL');
const tell = data => new Promise(resolve => process.send(data, resolve));
process.once('message', async input => {
  let db;
  try {
    const { mode, databasePath, context, request, grantId } = input;
    if (mode === 'read') {
      validate(context, request);
      db = new DatabaseSync(databasePath, { readOnly: true, timeout: 5000 });
      db.exec('PRAGMA query_only=ON; BEGIN;');
      const d = db.prepare('SELECT * FROM decisions WHERE operation_id=?').get(request.operationId);
      if (!d) { db.exec('ROLLBACK'); await tell({ status:'RESULT_UNKNOWN', code:'NO_DURABLE_COMMIT' }); return; }
      const decisionAt = Date.now(); // upper bound AFTER writer crash, never the stored precommit sample
      const b = JSON.parse(d.binding), rd = digest(request), cd = digest(context);
      const e = db.prepare('SELECT * FROM events WHERE id=?').get(request.eventId);
      const v = db.prepare('SELECT * FROM versions WHERE event_id=?').get(request.eventId);
      const r = db.prepare('SELECT * FROM receipts WHERE operation_id=?').get(request.operationId);
      const a = db.prepare('SELECT * FROM audit WHERE seq=?').get(d.audit_seq);
      const ap = db.prepare('SELECT * FROM approvals WHERE id=?').get(request.approvalId);
      const g = db.prepare('SELECT * FROM grants WHERE id=?').get(request.grantId);
      const cal = db.prepare('SELECT * FROM calendars WHERE id=?').get(request.calendarId);
      const expected = { operationId:request.operationId, requestDigest:rd, contextDigest:cd, calendarId:request.calendarId, eventId:request.eventId,
        grantId:request.grantId, generation:request.generation, approvalId:request.approvalId,
        snapshotDigest:digest({id:request.eventId,calendarId:request.calendarId,revision:1,title:request.title}),
        deadline:Math.min(g?.expires_at ?? 0,ap?.expires_at ?? 0), auditSequence:d.audit_seq };
      const good = d.request_digest===rd && d.context_digest===cd && canonical(b)===canonical(expected) &&
        r?.binding===canonical(b) && a?.binding===canonical(b) && a?.kind==='DECISION' && a?.operation_id===request.operationId &&
        e?.id===request.eventId && e?.calendar_id===request.calendarId && e?.revision===1 && e?.title===request.title &&
        v?.revision===1 && v?.snapshot_digest===b.snapshotDigest && ap?.consumed===1 && ap?.request_digest===rd && ap?.context_digest===cd &&
        ap?.grant_id===request.grantId && g?.generation===request.generation && g?.owner===context.owner && g?.tenant===context.tenant && g?.session===context.session &&
        cal?.owner===context.owner && cal?.tenant===context.tenant;
      if (!good) { db.exec('ROLLBACK'); await tell({status:'RESULT_UNKNOWN',code:'BINDING_MISMATCH'}); return; }
      const effectAt=Date.now(); // same committed transaction, a second readback observation, NOT a second commit
      db.exec('COMMIT');
      // Re-read the current grant after the read transaction; revoke-first disclosure remains closed.
      const fresh=db.prepare('SELECT state,generation FROM grants WHERE id=?').get(request.grantId);
      const releaseAt=Date.now();
      if (fresh.state!=='ACTIVE' || fresh.generation!==request.generation || cal.write_acl!==1 || releaseAt>=b.deadline) {
        await tell({status:'COMMITTED_RESULT_WITHHELD',code:fresh.state!=='ACTIVE'?'REVOKED':'DEADLINE_NOT_PROVEN',operationId:b.operationId,auditSequence:b.auditSequence}); return;
      }
      await tell({status:'SUCCEEDED',receipt:{...b,decisionAt,effectAt,measurement:'AFTER_CRASH_READBACK_UPPER_BOUNDS',twoDurableMoments:false},event:{...e}});
      return;
    }
    db = new DatabaseSync(databasePath, {timeout:5000,allowExtension:false});
    db.exec('PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL;');
    if (db.prepare('PRAGMA journal_mode').get().journal_mode!=='wal' || db.prepare('PRAGMA user_version').get().user_version!==13) throw Error('SCHEMA_OR_MODE_MISMATCH');
    db.exec('BEGIN IMMEDIATE');
    if (mode==='revoke') {
      exact(context, CONTEXT_KEYS);
      const g=db.prepare('SELECT * FROM grants WHERE id=?').get(grantId);
      if (!g || g.owner!==context.owner || g.tenant!==context.tenant || g.session!==context.session) throw Error('SOURCE_SCOPE');
      if (g.state==='ACTIVE') {
        db.prepare("INSERT INTO audit(kind,grant_id,binding) VALUES ('REVOKE',?,?)").run(grantId,canonical({grantId,generation:g.generation}));
        db.prepare("UPDATE grants SET state='REVOKED' WHERE id=?").run(grantId);
      }
      db.exec('COMMIT'); kill(); return;
    }
    if (mode!=='write') throw Error('INVALID_MODE');
    validate(context,request);
    // Duplicate detection precedes new writes and cannot reactivate approval or mutate an existing result.
    if (db.prepare('SELECT 1 FROM decisions WHERE operation_id=?').get(request.operationId)) { db.exec('ROLLBACK'); kill(); return; }
    const cal=db.prepare('SELECT * FROM calendars WHERE id=?').get(request.calendarId);
    const g=db.prepare('SELECT * FROM grants WHERE id=?').get(request.grantId);
    const ap=db.prepare('SELECT * FROM approvals WHERE id=?').get(request.approvalId);
    const rd=digest(request), cd=digest(context), observed=Date.now();
    if (!cal || cal.owner!==context.owner || cal.tenant!==context.tenant || cal.write_acl!==1 || !g ||
        g.calendar_id!==cal.id || g.owner!==context.owner || g.tenant!==context.tenant || g.session!==context.session ||
        g.generation!==request.generation || g.action!=='CREATE_OWN_EVENT') throw Error('SOURCE_SCOPE');
    if (g.state!=='ACTIVE' || observed>=g.expires_at) throw Error('CONSENT_INACTIVE');
    if (!ap || ap.grant_id!==g.id || ap.request_digest!==rd || ap.context_digest!==cd || ap.consumed!==0 || observed>=ap.expires_at) throw Error('APPROVAL_REQUIRED');
    const b={operationId:request.operationId,requestDigest:rd,contextDigest:cd,calendarId:cal.id,eventId:request.eventId,
      grantId:g.id,generation:g.generation,approvalId:ap.id,
      snapshotDigest:digest({id:request.eventId,calendarId:cal.id,revision:1,title:request.title}),deadline:Math.min(g.expires_at,ap.expires_at)};
    const seq=Number(db.prepare("INSERT INTO audit(kind,operation_id,grant_id,binding) VALUES ('DECISION',?,?,?)").run(request.operationId,g.id,'{}').lastInsertRowid);
    b.auditSequence=seq;
    const body=canonical(b);
    db.prepare('UPDATE audit SET binding=? WHERE seq=?').run(body,seq);
    db.prepare('INSERT INTO decisions VALUES (?,?,?,?,?,?)').run(request.operationId,seq,rd,cd,body,observed);
    db.prepare('INSERT INTO events VALUES (?,?,1,?)').run(request.eventId,cal.id,request.title);
    db.prepare('INSERT INTO versions VALUES (?,1,?)').run(request.eventId,b.snapshotDigest);
    db.prepare('UPDATE approvals SET consumed=1 WHERE id=? AND consumed=0').run(ap.id);
    db.prepare('INSERT INTO receipts VALUES (?,?)').run(request.operationId,body);
    if (process.env.B013_TEST_PHASE==='beforeCommit') kill();
    if (process.env.B013_TEST_PHASE==='fakeAckBeforeCommit') { await tell({status:'SUCCEEDED',fakeAck:true}); kill(); }
    if (process.env.B013_WAL_ARM) writeFileSync(process.env.B013_WAL_ARM,'armed');
    db.exec('COMMIT');
    // No ACK, receipt rewriting, checkpoint, graceful close, or second write. Actual abrupt process death.
    kill();
  } catch(e) {
    if (db?.isTransaction) db.exec('ROLLBACK');
    await tell({status:'DENIED',code:e.message});
  } finally { if(db) db.close(); process.disconnect(); }
});
