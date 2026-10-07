import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { fixture, createInput, prepared, seedCommitted, databaseState, regrant, corruptReceipt, NOW, owner } from './helpers.mjs';
import { PalacoCalendarAdapter } from '../src/calendar.mjs';
import { normalize, FIELDS } from '../src/value.mjs';

const denies = (fn, code) => assert.throws(fn, e => e.code === code);
function use(t, opts) { const f = fixture(opts); t.after(() => f.close()); return f; }

test('D012-P01 exact proposal digest and five-minute/grant-bound approval', t => {
  const f = use(t); const p = f.adapter.prepare('OWNER', createInput());
  denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposalId, digest: '0'.repeat(64) }), 'PROPOSAL_DIGEST_MISMATCH');
  const a = f.adapter.confirm('OWNER', { proposalId: p.proposalId, digest: p.digest });
  assert.equal(a.expiresAt, f.grant.expiresAt); assert.equal(a.execution, 'BLOCKED');
  assert.match(p.notice, /ene exacte/); assert.equal(p.after.start, '2026-10-05T08:00:00.000Z');
});
for (const action of ['CREATE_OWN_EVENT', 'MOVE_OWN_EVENT', 'EDIT_OWN_TEXT']) {
  test('D012-DENY-' + action + ' valid proposal and approval cannot authorize an effect', t => {
    const f = use(t); let input = createInput({ action });
    if (action !== 'CREATE_OWN_EVENT') {
      const hist = seedCommitted(f);
      input = createInput({ action, eventId: hist.eventId, expectedRevision: 1,
        changes: action === 'EDIT_OWN_TEXT' ? { title: 'New synthetic title' } : { start: '2026-10-06T10:00:00+02:00', end: '2026-10-06T11:00:00+02:00', timeZone: 'Europe/Amsterdam' } });
    }
    const p = prepared(f, input), before = databaseState(f.db), counts = { ...f.state.counts };
    denies(() => f.adapter.execute('HANNIE', { ...p, supported: true }), 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED');
    assert.equal(databaseState(f.db), before); assert.deepEqual(f.state.counts, counts);
  });
}
test('D012-D01 execute refuses before argument getters, callbacks, flags and borrowed methods', t => {
  const f = use(t), before = databaseState(f.db);
  const poison = new Proxy({}, { get() { throw new Error('MUST NOT TOUCH'); } });
  for (const receiver of [f.adapter, {}, null, PalacoCalendarAdapter.prototype]) {
    denies(() => f.adapter.execute.call(receiver, poison, poison, { skipGuard: true }), 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED');
  }
  denies(() => PalacoCalendarAdapter.prototype.execute.call({}, poison), 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED');
  assert.equal(databaseState(f.db), before);
});
test('D012-D02 immutable instance/prototype/class and no subclass execute route', t => {
  const f = use(t);
  assert.ok(Object.isFrozen(f.adapter)); assert.ok(Object.isFrozen(PalacoCalendarAdapter)); assert.ok(Object.isFrozen(PalacoCalendarAdapter.prototype));
  assert.throws(() => { f.adapter.execute = () => 'ALLOW'; }, TypeError);
  assert.throws(() => Object.defineProperty(f.adapter, 'execute', { value() {} }), TypeError);
  class Bypass extends PalacoCalendarAdapter {}
  denies(() => new Bypass(f.dependencies), 'SUBCLASS_UNSUPPORTED');
  assert.equal(f.adapter.status().D010, 'OPEN');
});
test('D012-D03 direct import, package exports and factory have the same denial', async t => {
  const f = use(t); const root = await import('@palaco/hannie-agenda-candidate');
  const direct = await import('@palaco/hannie-agenda-candidate/calendar');
  assert.equal(root.PalacoCalendarAdapter, direct.PalacoCalendarAdapter);
  const other = root.createPalacoCalendarAdapter(f.dependencies); t.after(() => other.close());
  denies(() => other.execute(), 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED');
});
test('D012-P02 exact idempotent prepare is stable; altered input or origin conflicts', t => {
  const f = use(t), input = createInput(), p = f.adapter.prepare('OWNER', input);
  assert.deepEqual(f.adapter.prepare('OWNER', input), p);
  denies(() => f.adapter.prepare('OWNER', { ...input, origin: 'HARA' }), 'IDEMPOTENCY_CONFLICT');
  denies(() => f.adapter.prepare('OWNER', { ...input, changes: { ...input.changes, title: 'Altered' } }), 'IDEMPOTENCY_CONFLICT');
});
test('D012-P03 read-only grant can prepare but cannot confirm', t => {
  const f = use(t); regrant(f, { actions: [] });
  const p = f.adapter.prepare('OWNER', createInput());
  denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposalId, digest: p.digest }), 'WRITE_GRANT_REQUIRED');
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM events').get().n, 0);
});
test('D012-G01 revoked generation cannot be revived by regrant or rollback', t => {
  const f = use(t), p = prepared(f);
  f.adapter.revoke('OWNER', { calendarId: p.input.calendarId, grantId: f.grant.id });
  assert.equal(f.db.prepare('SELECT state FROM grants WHERE id=?').get(f.grant.id).state, 'REVOKED');
  regrant(f);
  denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposal.proposalId, digest: p.proposal.digest }), 'CONSENT_GENERATION_CHANGED');
  f.state.now = NOW - 1;
  denies(() => f.adapter.readEvent('HANNIE', { calendarId: p.input.calendarId, eventId: 'missing', purpose: 'schedule' }), 'TEMPORAL_UNCERTAIN');
});
test('D012-G02 expiry is terminal and durable across restart', t => {
  const f = use(t), h = seedCommitted(f);
  f.state.now = f.grant.expiresAt;
  denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), 'CONSENT_INACTIVE');
  assert.equal(f.db.prepare('SELECT state FROM grants WHERE id=?').get(f.grant.id).state, 'EXPIRED');
  const newAdapter = new PalacoCalendarAdapter(f.dependencies); t.after(() => newAdapter.close());
  f.state.now -= 1;
  denies(() => newAdapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), 'TEMPORAL_UNCERTAIN');
});
for (const key of ['subject', 'tenant', 'citadel', 'world', 'session']) {
  test('D012-I-' + key + ' context isolation', t => {
    const f = use(t), h = seedCommitted(f);
    f.state.context = actor => ({ ...owner, actor, [key]: 'fixture-other' });
    const r = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
    assert.equal(r.status, 'RESULT_UNKNOWN'); assert.equal(r.event, undefined); assert.equal(r.receiptId, undefined);
  });
}
test('D012-I06 context change, admission loss and policy change during callbacks deny content', t => {
  const f = use(t), h = seedCommitted(f); let count = 0;
  f.state.context = actor => ({ ...owner, actor, session: ++count % 2 ? owner.session : 'other' });
  denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), 'AUTH_CONTEXT_CHANGED');
  f.state.context = actor => ({ ...owner, actor, admitted: false });
  denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), 'AUTH_CONTEXT_DENIED');
  f.state.context = actor => ({ ...owner, actor }); f.state.policy.version = 'fixture-policy-v2';
  denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }), 'GRANT_BINDING_CHANGED');
});
test('D012-I07 asynchronous and thenable dependencies are rejected', t => {
  const f = use(t);
  denies(() => new PalacoCalendarAdapter({ ...f.dependencies, resolveContext: async () => owner }), 'SYNC_DEPENDENCY_REQUIRED');
  f.state.context = () => Promise.resolve(owner);
  denies(() => f.adapter.prepare('OWNER', createInput()), 'SYNC_DEPENDENCY_REQUIRED');
});
test('D012-P04 unknown fields, action escalation and third-party effects are rejected', t => {
  const f = use(t);
  for (const changes of [{ ...createInput().changes, attendees: ['person'] }, { ...createInput().changes, location: 'other' }]) {
    denies(() => f.adapter.prepare('OWNER', createInput({ changes })), 'INVALID_INPUT');
  }
  for (const action of ['DELETE_EVENT', 'INVITE', 'EDIT_OWN_EVENT', 'SYNC', 'CREATE']) denies(() => f.adapter.prepare('OWNER', createInput({ action })), 'INVALID_ACTION');
  denies(() => f.adapter.prepare('CHING_CHING', createInput()), 'RECIPIENT_DENIED');
  denies(() => f.adapter.issueGrant('CHING_CHING', {}), 'INVALID_INPUT');
});
test('D012-T01 timezone offset, spring gap and autumn-fold validation', () => {
  const input = createInput().changes;
  for (const changes of [
    { ...input, start: '2026-03-29T02:30:00+01:00', end: '2026-03-29T04:00:00+02:00' },
    { ...input, start: '2026-10-05T10:00:00+01:00' },
    { ...input, start: '2026-02-30T10:00:00+01:00' },
  ]) denies(() => normalize('CREATE_OWN_EVENT', changes), 'DST_OR_OFFSET_MISMATCH');
  denies(() => normalize('CREATE_OWN_EVENT', { ...input, start: '2026-10-05T10:00:00' }), 'OFFSET_REQUIRED');
  const a = normalize('CREATE_OWN_EVENT', { ...input, start: '2026-10-25T02:30:00+02:00', end: '2026-10-25T03:30:00+01:00' });
  const b = normalize('CREATE_OWN_EVENT', { ...input, start: '2026-10-25T02:30:00+01:00', end: '2026-10-25T03:30:00+01:00' });
  assert.equal(Date.parse(b.start) - Date.parse(a.start), 3600000);
});
test('D012-R01 scope/purpose/field projections and receipt rights are separate', t => {
  const f = use(t), h = seedCommitted(f);
  regrant(f, { fields: ['title'], actions: [] });
  assert.deepEqual(f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'schedule' }).event, { title: 'Synthetic title' });
  const r = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
  assert.equal(r.status, 'SUCCEEDED'); assert.deepEqual(r.event, { title: 'Synthetic title' });
  denies(() => f.adapter.readEvent('HANNIE', { calendarId: h.input.calendarId, eventId: h.eventId, purpose: 'other' }), 'PURPOSE_DENIED');
  denies(() => f.adapter.prepare('OWNER', createInput()), 'FIELD_DENIED');
  regrant(f, { fields: ['title'], receiptRecipients: ['OWNER'] });
  const blocked = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
  assert.equal(blocked.receiptId, undefined); assert.equal(blocked.event, undefined);
});
test('D012-R02 OWNER minimal historical receipt after revoke has no content; HANNIE has no receipt identity', t => {
  const f = use(t), h = seedCommitted(f), before = databaseState(f.db);
  f.adapter.revoke('OWNER', { calendarId: h.input.calendarId, grantId: f.grant.id });
  const r = f.adapter.recover('OWNER', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
  assert.equal(r.status, 'COMMITTED_RESULT_WITHHELD'); assert.equal(r.event, undefined); assert.equal(r.eventId, undefined);
  const s = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
  assert.equal(s.status, 'RESULT_UNKNOWN'); assert.equal(s.receiptId, undefined); assert.equal(s.operationId, undefined);
  assert.equal(databaseState(f.db), before);
});
test('D012-R03 historical version is not presented as current; repeated recovery performs no effects', t => {
  const f = use(t), h = seedCommitted(f);
  seedCommitted(f, prepared(f, createInput({ action: 'EDIT_OWN_TEXT', eventId: h.eventId, expectedRevision: 1, changes: { title: 'Current title' } })));
  const before = databaseState(f.db);
  for (let i = 0; i < 2; i++) {
    const r = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
    assert.equal(r.status, 'SUCCEEDED'); assert.equal(r.historical, true); assert.equal(r.currentRevision, 2);
    assert.equal(r.event.title, 'Synthetic title');
  }
  assert.equal(databaseState(f.db), before);
});
for (const field of ['requestRef', 'idempotencyKey', 'contextDigest', 'proposalDigest', 'eventId', 'eventRevision', 'operationId', 'grantRevision', 'auditSequence', 'snapshotDigest', 'approvalId', 'policyVersion', 'bindingRevision']) {
  test('D012-RB-' + field + ' corrupted receipt gives no success or content', t => {
    const f = use(t), h = seedCommitted(f);
    corruptReceipt(f, h.proposal.proposalId, r => ({ ...r, [field]: typeof r[field] === 'number' ? r[field] + 1 : 'corrupt' }));
    const r = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
    assert.equal(r.status, 'RESULT_UNKNOWN'); assert.equal(r.event, undefined); assert.equal(r.receiptId, undefined);
  });
}
test('D012-R04 missing receipt never becomes success or an automatic retry', t => {
  const f = use(t), p = prepared(f), before = databaseState(f.db);
  assert.equal(f.adapter.recover('HANNIE', { proposalId: p.proposal.proposalId, digest: p.proposal.digest }).status, 'RESULT_UNKNOWN');
  assert.equal(databaseState(f.db), before);
});
test('D012-S01 source revision change blocks stale approval', t => {
  const f = use(t), h = seedCommitted(f);
  const p = f.adapter.prepare('OWNER', createInput({ action: 'EDIT_OWN_TEXT', eventId: h.eventId, expectedRevision: 1, changes: { title: 'Proposal title' } }));
  f.db.prepare('UPDATE events SET revision=2 WHERE id=?').run(h.eventId);
  denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposalId, digest: p.digest }), 'REVISION_CONFLICT');
});
test('D012-S02 failed successor keeps old proposal superseded and old approval invalid', t => {
  const f = use(t), p = prepared(f);
  const replacement = createInput({ changes: { ...p.input.changes, title: '' } });
  denies(() => f.adapter.revise('OWNER', { proposalId: p.proposal.proposalId, digest: p.proposal.digest, replacement }), 'INVALID_TITLE');
  assert.equal(f.db.prepare('SELECT state FROM proposals WHERE id=?').get(p.proposal.proposalId).state, 'SUPERSEDED');
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM approvals WHERE proposal_id=?').get(p.proposal.proposalId).n, 0);
  denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposal.proposalId, digest: p.proposal.digest }), 'PROPOSAL_INACTIVE');
});
for (const [total, yes] of [[3, 2], [4, 3], [5, 3], [6, 4], [7, 5]]) {
  test('D012-V-' + total + ' threshold approves advice but execute stays denied', t => {
    const f = use(t), p = f.adapter.prepare('HANNIE', createInput({ origin: 'HARA' }));
    denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposalId, digest: p.digest }), 'REVIEW_PENDING');
    assert.equal(f.adapter.recordReview('REVIEWER', { proposalId: p.proposalId, digest: p.digest, total, yes, concern: false }).state, 'APPROVED');
    f.adapter.confirm('OWNER', { proposalId: p.proposalId, digest: p.digest });
    denies(() => f.adapter.execute('HANNIE', p), 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED');
  });
}
test('D012-C01 target concern spans new requests, actors/actions/sessions and selected reassessment only', t => {
  const f = use(t), h = seedCommitted(f);
  const input = createInput({ action: 'EDIT_OWN_TEXT', eventId: h.eventId, expectedRevision: 1, changes: { title: 'First proposal' } });
  const p = prepared(f, input);
  f.adapter.recordReview('REVIEWER', { proposalId: p.proposal.proposalId, digest: p.proposal.digest, total: 3, yes: 3, concern: true });
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM approvals WHERE consumed=0').get().n, 0);
  const q = f.adapter.prepare('OWNER', createInput({ action: 'MOVE_OWN_EVENT', eventId: h.eventId, expectedRevision: 1,
    changes: { start: '2026-10-06T10:00:00+02:00', end: '2026-10-06T11:00:00+02:00', timeZone: 'Europe/Amsterdam' } }));
  denies(() => f.adapter.confirm('OWNER', { proposalId: q.proposalId, digest: q.digest }), 'REVIEW_PENDING');
  f.adapter.recordReview('REVIEWER', { proposalId: q.proposalId, digest: q.digest, total: 3, yes: 3, concern: false, reassess: true, expectedConcernRevision: 1 });
  f.adapter.confirm('OWNER', { proposalId: q.proposalId, digest: q.digest });
  denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposal.proposalId, digest: p.proposal.digest }), 'REVIEW_PENDING');
  f.state.context = actor => ({ ...owner, actor, session: 'fixture-session-B' });
  regrant(f);
  const s = f.adapter.prepare('OWNER', { ...input, requestRef: 'new-session-request', idempotencyKey: 'new-session-key' });
  denies(() => f.adapter.confirm('OWNER', { proposalId: s.proposalId, digest: s.digest }), 'REVIEW_PENDING');
});
test('D012-C02 concern survives revision and owner cannot overrule it', t => {
  const f = use(t), p = prepared(f);
  f.adapter.recordReview('REVIEWER', { proposalId: p.proposal.proposalId, digest: p.proposal.digest, total: 3, yes: 0, concern: true });
  const q = f.adapter.revise('OWNER', { proposalId: p.proposal.proposalId, digest: p.proposal.digest, replacement: createInput() });
  assert.equal(q.supersedes, p.proposal.proposalId);
  denies(() => f.adapter.confirm('OWNER', { proposalId: q.proposalId, digest: q.digest }), 'REVIEW_PENDING');
  denies(() => f.adapter.resolveInternalConflict('OWNER', { proposalId: q.proposalId, digest: q.digest }), 'REVIEW_PENDING');
});
test('D012-C03 owner resolves dissent without extending scope or grant', t => {
  const f = use(t), p = f.adapter.prepare('HANNIE', createInput({ origin: 'HARA' }));
  f.adapter.recordReview('REVIEWER', { proposalId: p.proposalId, digest: p.digest, total: 3, yes: 1, concern: false });
  assert.equal(f.adapter.resolveInternalConflict('OWNER', { proposalId: p.proposalId, digest: p.digest }).writeAuthority, false);
  f.adapter.confirm('OWNER', { proposalId: p.proposalId, digest: p.digest });
});
test('D012-S03 schema rejects historical 301; returned snapshots are detached and frozen', t => {
  const f = use(t), p = f.adapter.prepare('OWNER', createInput());
  assert.ok(Object.isFrozen(p.after)); assert.throws(() => { p.after.title = 'changed'; }, TypeError);
  f.db.exec('PRAGMA user_version=301');
  denies(() => new PalacoCalendarAdapter(f.dependencies), 'SCHEMA_MISMATCH');
});
test('D012-S04 immutable receipt/version/audit and no title/note in audit', t => {
  const f = use(t), h = seedCommitted(f);
  for (const table of ['event_versions', 'receipts', 'mutation_audit']) assert.throws(() => f.db.exec('DELETE FROM ' + table), /IMMUTABLE/);
  const audit = f.db.prepare('SELECT body FROM mutation_audit').get().body;
  assert.ok(!audit.includes('Synthetic title')); assert.ok(!audit.includes('Synthetic private note'));
  assert.equal(f.adapter.recover('OWNER', { proposalId: h.proposal.proposalId, digest: h.proposal.digest }).status, 'SUCCEEDED');
});
test('D012-O01 HANNIE origin flag cannot impersonate an authenticated owner instruction', t => {
  const f = use(t);
  denies(() => f.adapter.prepare('HANNIE', createInput()), 'OWNER_INSTRUCTION_REQUIRED');
  const p = f.adapter.prepare('HANNIE', createInput({ origin: 'HARA' }));
  denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposalId, digest: p.digest }), 'REVIEW_PENDING');
});
test('D012-R05 current event/version mismatch is not silently presented as a valid recovery', t => {
  const f = use(t), h = seedCommitted(f);
  f.db.prepare('UPDATE events SET snapshot=? WHERE id=?').run(JSON.stringify({ ...h.proposal.after, title: 'Corrupt current row' }), h.eventId);
  const r = f.adapter.recover('OWNER', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
  assert.equal(r.status, 'RESULT_UNKNOWN'); assert.equal(r.event, undefined);
});
test('D012-G03 expired consent denial inside a transaction remains terminal after rollback', t => {
  const f = use(t), p = prepared(f); let calls = 0;
  f.state.contextHook = () => { if (++calls === 5) f.state.now = f.grant.expiresAt; };
  denies(() => f.adapter.confirm('OWNER', { proposalId: p.proposal.proposalId, digest: p.proposal.digest }), 'CONSENT_INACTIVE');
  assert.equal(f.db.prepare('SELECT state FROM grants WHERE id=?').get(f.grant.id).state, 'EXPIRED');
});
test('D012-R06 OWNER explicit receipt permission with zero content fields releases only metadata', t => {
  const f = use(t), h = seedCommitted(f);
  regrant(f, { fields: [], actions: [] });
  const r = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
  assert.equal(r.status, 'COMMITTED_RESULT_WITHHELD'); assert.equal(r.event, undefined);
});
test('D012-D04 test fixture is outside package exports', async () => {
  await assert.rejects(() => import('@palaco/hannie-agenda-candidate/tests/helpers.mjs'), e => e.code === 'ERR_PACKAGE_PATH_NOT_EXPORTED');
});
test('D012-R07 current version advanced during recovery callback is marked historical after wait', t => {
  const f = use(t), h = seedCommitted(f); let once = true;
  f.state.releaseHook = () => {
    if (once) {
      once = false;
      seedCommitted(f, prepared(f, createInput({ action: 'EDIT_OWN_TEXT', eventId: h.eventId, expectedRevision: 1, changes: { title: 'New current title' } })));
    }
  };
  const r = f.adapter.recover('HANNIE', { proposalId: h.proposal.proposalId, digest: h.proposal.digest });
  assert.equal(r.status, 'SUCCEEDED'); assert.equal(r.historical, true); assert.equal(r.currentRevision, 2);
  assert.equal(r.event.title, 'Synthetic title');
});
