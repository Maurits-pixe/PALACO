import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { PalacoCalendarAdapter } from '../src/calendar.mjs';
import { digest, canonical, FIELDS, ACTIONS } from '../src/value.mjs';

export const NOW = Date.parse('2026-10-04T12:00:00Z');
export const owner = { admitted: true, subject: 'fixture-owner-A', tenant: 'fixture-tenant-A', citadel: 'fixture-citadel-A', world: 'fixture-world-A', session: 'fixture-session-A', actor: 'OWNER' };
export const sessionKey = c => digest({ scope: digest({ subject: c.subject, tenant: c.tenant, citadel: c.citadel, world: c.world }), session: c.session });
export function fixture(options = {}) {
  const dir = options.dir || mkdtempSync(join(tmpdir(), 'palaco-d012-'));
  const path = join(dir, 'calendar.sqlite');
  const state = { now: NOW, context: h => ({ ...owner, actor: h }), policy: { version: 'fixture-policy-v1', enabled: true },
    contextHook: () => {}, policyHook: () => {}, releaseHook: () => {}, counts: { context: 0, policy: 0, clock: 0, release: 0 } };
  const dependencies = {
    databasePath: path,
    resolveContext: h => { state.counts.context++; state.contextHook(); return state.context(h); },
    policyProvider: () => { state.counts.policy++; state.policyHook(); return state.policy; },
    clock: () => { state.counts.clock++; return options.realClock ? Date.now() : state.now; },
    beforeRelease: op => { state.counts.release++; state.releaseHook(op); },
  };
  const adapter = new PalacoCalendarAdapter(dependencies);
  adapter.registerOwnCalendar('OWNER', { calendarId: 'fixture-own-calendar-A', name: 'Synthetic calendar' });
  const grant = adapter.issueGrant('OWNER', { calendarId: 'fixture-own-calendar-A', purpose: 'schedule',
    recipients: ['OWNER', 'HANNIE', 'REVIEWER'], fields: [...FIELDS], receiptRecipients: ['OWNER', 'HANNIE'],
    actions: Object.keys(ACTIONS), reviewAllowed: true, expiresAt: (options.realClock ? Date.now() : NOW) + (options.expiresMs || 60000) });
  const db = new DatabaseSync(path, { timeout: 5000 });
  return { dir, path, adapter, db, state, grant, dependencies,
    close() { adapter.close(); db.close(); if (!options.dir) rmSync(dir, { recursive: true, force: true }); } };
}
let number = 0;
export function createInput(overrides = {}) {
  const n = ++number;
  return { requestRef: 'fixture-request-' + n, idempotencyKey: 'fixture-key-' + n, calendarId: 'fixture-own-calendar-A',
    purpose: 'schedule', action: 'CREATE_OWN_EVENT', origin: 'OWNER_DIRECT',
    changes: { title: 'Synthetic title', note: 'Synthetic private note', start: '2026-10-05T10:00:00+02:00', end: '2026-10-05T11:00:00+02:00', timeZone: 'Europe/Amsterdam' },
    ...overrides };
}
export function prepared(f, input = createInput()) {
  const proposal = f.adapter.prepare(input.origin === 'OWNER_DIRECT' ? 'OWNER' : 'HANNIE', input);
  const approval = f.adapter.confirm('OWNER', { proposalId: proposal.proposalId, digest: proposal.digest });
  return { proposal, approval, input };
}
export function databaseState(db) {
  const tables = ['events', 'event_versions', 'receipts', 'mutation_audit', 'approvals', 'proposals', 'concerns', 'review_history'];
  return canonical(Object.fromEntries(tables.map(t => [t, db.prepare('SELECT * FROM ' + t + ' ORDER BY 1').all().map(row => ({ ...row }))])));
}
// Explicit privileged synthetic history; NOT an adapter execution, reconstruction of old code or runtime export.
export function seedCommitted(f, p = prepared(f)) {
  const row = f.db.prepare('SELECT * FROM proposals WHERE id=?').get(p.proposal.proposalId), b = JSON.parse(row.body);
  const ap = f.db.prepare('SELECT * FROM approvals WHERE proposal_id=?').get(b.id);
  const auditSequence = f.db.prepare('SELECT COALESCE(MAX(seq),0)+1 AS n FROM mutation_audit').get().n;
  const r = { id: 'fixture-receipt-' + b.id, proposalId: b.id, proposalDigest: row.digest, contextDigest: digest(b.context),
    requestRef: b.requestRef, idempotencyKey: b.idempotencyKey, calendarId: b.calendarId, eventId: b.eventId,
    eventRevision: b.expectedRevision + 1, grantId: b.grant.id, grantRevision: b.grant.revision,
    policyVersion: b.policyVersion, bindingRevision: b.bindingRevision, snapshotDigest: digest(b.after),
    approvalId: ap.id, auditSequence, operationId: 'fixture-operation-' + b.id };
  f.db.exec('BEGIN IMMEDIATE');
  try {
    f.db.prepare('INSERT INTO events(id,calendar_id,revision,snapshot) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot')
      .run(b.eventId, b.calendarId, r.eventRevision, canonical(b.after));
    f.db.prepare('INSERT INTO event_versions(event_id,revision,snapshot,digest) VALUES (?,?,?,?)').run(b.eventId, r.eventRevision, canonical(b.after), digest(b.after));
    f.db.prepare('INSERT INTO mutation_audit(seq,operation_id,body) VALUES (?,?,?)').run(auditSequence, r.operationId, canonical(r));
    f.db.prepare('INSERT INTO receipts(id,proposal_id,body) VALUES (?,?,?)').run(r.id, b.id, canonical(r));
    f.db.prepare('UPDATE approvals SET consumed=1 WHERE id=?').run(ap.id);
    f.db.prepare("UPDATE proposals SET state='COMMITTED' WHERE id=?").run(b.id);
    f.db.exec('COMMIT');
  } catch (e) { f.db.exec('ROLLBACK'); throw e; }
  return { ...p, receipt: r, eventId: b.eventId };
}
export function regrant(f, overrides = {}) {
  return f.adapter.issueGrant('OWNER', { calendarId: 'fixture-own-calendar-A', purpose: 'schedule',
    recipients: ['OWNER', 'HANNIE', 'REVIEWER'], fields: [...FIELDS], receiptRecipients: ['OWNER', 'HANNIE'],
    actions: Object.keys(ACTIONS), expiresAt: f.state.now + 60000, reviewAllowed: true, ...overrides });
}
export function corruptReceipt(f, proposalId, change) {
  f.db.exec('DROP TRIGGER receipts_no_update');
  const r = f.db.prepare('SELECT * FROM receipts WHERE proposal_id=?').get(proposalId);
  f.db.prepare('UPDATE receipts SET body=? WHERE id=?').run(canonical(change(JSON.parse(r.body))), r.id);
  f.db.exec("CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT, 'IMMUTABLE'); END");
}
export function waitUntil(time) {
  const array = new Int32Array(new SharedArrayBuffer(4));
  while (Date.now() < time) Atomics.wait(array, 0, 0, Math.min(20, time - Date.now()));
}
