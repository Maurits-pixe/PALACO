import { DatabaseSync, constants } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { CalendarError, deny, exact, id, canonical, digest, detached, normalize, FIELDS, ACTIONS, THRESHOLDS } from './value.mjs';

const VERSION = '0.3.3-d012.1';
const ROLES = ['OWNER', 'HANNIE', 'REVIEWER', 'HARAM', 'CHING_CHING'];
const CONTEXT_FIELDS = ['admitted', 'subject', 'tenant', 'citadel', 'world', 'session', 'actor'];
const scope = c => digest({ subject: c.subject, tenant: c.tenant, citadel: c.citadel, world: c.world });
const session = c => digest({ scope: scope(c), session: c.session });
const unknown = code => detached({ status: 'RESULT_UNKNOWN', code });
const mutationDeny = Object.freeze(function execute() { deny('STORAGE_EFFECT_DEADLINE_UNSUPPORTED'); });
const same = (a, b) => canonical(a) === canonical(b);

export class PalacoCalendarAdapter {
  #db; #resolve; #policy; #clock; #beforeRelease; #highest = 0;
  constructor(options) {
    if (new.target !== PalacoCalendarAdapter) deny('SUBCLASS_UNSUPPORTED');
    exact(options, ['databasePath', 'resolveContext', 'policyProvider', 'clock', 'beforeRelease'], ['databasePath', 'resolveContext', 'policyProvider', 'clock']);
    for (const k of ['resolveContext', 'policyProvider', 'clock']) {
      if (typeof options[k] !== 'function' || options[k].constructor.name === 'AsyncFunction') deny('SYNC_DEPENDENCY_REQUIRED');
    }
    if (options.beforeRelease !== undefined && (typeof options.beforeRelease !== 'function' || options.beforeRelease.constructor.name === 'AsyncFunction')) deny('SYNC_DEPENDENCY_REQUIRED');
    this.#resolve = options.resolveContext; this.#policy = options.policyProvider; this.#clock = options.clock;
    this.#beforeRelease = options.beforeRelease || (() => undefined);
    this.#db = new DatabaseSync(options.databasePath, { timeout: 5000, allowExtension: false, defensive: true });
    this.#db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;');
    const v = this.#db.prepare('PRAGMA user_version').get().user_version;
    if (v !== 0 && v !== 1) { this.#db.close(); deny('SCHEMA_MISMATCH'); }
    this.#db.exec(readFileSync(new URL('./schema.sql', import.meta.url), 'utf8'));
    // Runtime SQL cannot mutate calendar-effect tables. Fixtures use a separate privileged connection.
    this.#db.setAuthorizer((action, table) => {
      if ([constants.SQLITE_INSERT, constants.SQLITE_UPDATE, constants.SQLITE_DELETE].includes(action) &&
          ['events', 'event_versions', 'receipts', 'mutation_audit'].includes(table)) return constants.SQLITE_DENY;
      return constants.SQLITE_OK;
    });
    Object.defineProperty(this, 'execute', { value: mutationDeny, writable: false, configurable: false });
    Object.freeze(this);
  }
  #sync(fn, ...args) {
    const value = fn(...args);
    if (value && typeof value.then === 'function') { Promise.resolve(value).catch(() => {}); deny('SYNC_DEPENDENCY_REQUIRED'); }
    return value;
  }
  #context(handle) {
    const c = detached(exact(this.#sync(this.#resolve, handle), CONTEXT_FIELDS));
    if (c.admitted !== true || !ROLES.includes(c.actor)) deny('AUTH_CONTEXT_DENIED');
    for (const k of CONTEXT_FIELDS.filter(k => !['admitted', 'actor'].includes(k))) id(c[k]);
    return c;
  }
  #frame(handle, expected = null) {
    // No earlier time sample is used to authorize a result after these potentially waiting calls.
    const c = this.#context(handle), p = detached(exact(this.#sync(this.#policy), ['version', 'enabled']));
    const c2 = this.#context(handle), p2 = detached(exact(this.#sync(this.#policy), ['version', 'enabled']));
    if (!same(c, c2) || !same(p, p2) || (expected && !same(c, expected))) deny('AUTH_CONTEXT_CHANGED');
    if (p.enabled !== true) deny('POLICY_BLOCKED');
    id(p.version);
    return { c, p };
  }
  #sample() {
    const start = performance.now(), value = this.#sync(this.#clock);
    if (!Number.isSafeInteger(value) || value < 0 || performance.now() - start > 25) deny('TEMPORAL_UNCERTAIN');
    return value;
  }
  #observe() {
    const before = this.#db.prepare("SELECT value FROM d012_meta WHERE key='highest_time'").get().value;
    const sampled = this.#sample();
    if (sampled < Math.max(before, this.#highest)) deny('TEMPORAL_UNCERTAIN');
    if (sampled > before) {
      const own = !this.#db.isTransaction;
      if (own) this.#db.exec('BEGIN IMMEDIATE');
      try {
        const high = this.#db.prepare("SELECT value FROM d012_meta WHERE key='highest_time'").get().value;
        const now = this.#sample(); // after lock wait
        if (now < Math.max(high, this.#highest)) deny('TEMPORAL_UNCERTAIN');
        if (now > high) {
          this.#db.prepare('INSERT INTO clock_observations(previous,observed) VALUES (?,?)').run(high, now);
          this.#db.prepare("UPDATE d012_meta SET value=? WHERE key='highest_time'").run(now);
        }
        if (own) this.#db.exec('COMMIT');
        this.#highest = Math.max(this.#highest, now);
      } catch (e) { if (own && this.#db.isTransaction) this.#db.exec('ROLLBACK'); throw e; }
    }
    const final = this.#sample(); // after all storage waits; no dependency follows this in the release fence
    if (final < Math.max(before, this.#highest)) deny('TEMPORAL_UNCERTAIN');
    this.#highest = final;
    return final;
  }
  #tx(fn) {
    if (this.#db.isTransaction) deny('REENTRANCY_DENIED');
    this.#db.exec('BEGIN IMMEDIATE');
    try { const result = fn(); this.#db.exec('COMMIT'); return result; }
    catch (e) {
      if (this.#db.isTransaction) this.#db.exec('ROLLBACK');
      // Retain a denied attempt's observed high-water mark outside its rolled-back transaction.
      const now = this.#observe();
      this.#db.prepare("UPDATE grants SET state='EXPIRED' WHERE state='ACTIVE' AND json_extract(body,'$.expiresAt')<=?").run(now);
      throw e;
    }
  }
  #calendar(c, calendarId) {
    const row = this.#db.prepare('SELECT * FROM calendars WHERE id=?').get(id(calendarId));
    if (!row || row.scope !== scope(c)) deny('SOURCE_SCOPE');
    const b = JSON.parse(row.body);
    if (b.owner !== c.subject || b.shared || b.scope !== scope(c)) deny('SOURCE_SCOPE');
    return b;
  }
  #authorize(handle, opts) {
    const { c, p } = this.#frame(handle, opts.context);
    this.#observe(); // persist temporal evidence before loading the current authorization snapshot
    const freshFrame = this.#frame(handle, c); // context/policy must be reacquired after a real storage lock wait
    if (!same(p, freshFrame.p)) deny('POLICY_CHANGED');
    const cal = this.#calendar(c, opts.calendarId);
    const row = this.#db.prepare('SELECT * FROM grants WHERE calendar_id=? ORDER BY revision DESC LIMIT 1').get(cal.id);
    const g = row ? JSON.parse(row.body) : null;
    const durableHigh = this.#db.prepare("SELECT value FROM d012_meta WHERE key='highest_time'").get().value;
    const now = this.#sample(); // AFTER context, policy and storage waits; no callback or DB access on ALLOW
    if (now < Math.max(durableHigh, this.#highest)) deny('TEMPORAL_UNCERTAIN');
    this.#highest = now;
    if (row && row.state === 'ACTIVE' && now >= g.expiresAt) {
      this.#db.prepare("UPDATE grants SET state='EXPIRED' WHERE id=? AND state='ACTIVE'").run(row.id);
      deny('CONSENT_INACTIVE');
    }
    if (!row || row.state !== 'ACTIVE') deny('CONSENT_INACTIVE');
    if (g.session !== session(c) || g.policyVersion !== p.version || g.bindingRevision !== cal.bindingRevision) deny('GRANT_BINDING_CHANGED');
    if (g.purpose !== opts.purpose) deny('PURPOSE_DENIED');
    if (opts.bound && (row.id !== opts.bound.id || row.revision !== opts.bound.revision)) deny('CONSENT_GENERATION_CHANGED');
    const recipient = opts.recipient || c.actor;
    if (!g.recipients.includes(recipient)) deny('RECIPIENT_DENIED');
    if ((opts.fields || []).some(f => !g.fields.includes(f))) deny('FIELD_DENIED');
    if (opts.mode === 'write' && (!cal.writeAcl || !g.actions.includes(opts.action))) deny('WRITE_GRANT_REQUIRED');
    if (opts.mode === 'receipt' && !g.receiptRecipients.includes(c.actor)) deny('RECEIPT_ACCESS_DENIED');
    if (opts.mode === 'review' && (c.actor !== 'REVIEWER' || !g.reviewAllowed)) deny('REVIEW_RIGHT_REQUIRED');
    return { c, p, cal, g: { ...g, id: row.id, revision: row.revision }, now };
  }
  #event(calendarId, eventId) {
    const e = this.#db.prepare('SELECT * FROM events WHERE id=? AND calendar_id=?').get(id(eventId), calendarId);
    if (!e) deny('SOURCE_SCOPE');
    return { id: e.id, revision: e.revision, snapshot: detached(JSON.parse(e.snapshot)) };
  }
  #proposal(handle, proposalId, expectedDigest) {
    const frame = this.#frame(handle);
    const row = this.#db.prepare('SELECT * FROM proposals WHERE id=?').get(id(proposalId));
    if (!row) deny('PROPOSAL_UNAVAILABLE');
    const body = JSON.parse(row.body);
    if (session(frame.c) !== session(body.context)) deny('SOURCE_SCOPE');
    if (expectedDigest !== row.digest || digest(body) !== row.digest || body.id !== row.id ||
        row.context_key !== digest(body.context) || row.request_ref !== body.requestRef || row.idem_key !== body.idempotencyKey) deny('PROPOSAL_DIGEST_MISMATCH');
    this.#calendar(frame.c, body.calendarId);
    return { row, body, frame };
  }
  #source(body) {
    if (body.action === 'CREATE_OWN_EVENT') return;
    const e = this.#event(body.calendarId, body.eventId);
    if (e.revision !== body.expectedRevision || !same(e.snapshot, body.before)) deny('REVISION_CONFLICT');
  }
  #ready(proposal) {
    if (!['PROPOSED', 'READY'].includes(proposal.row.state)) deny('PROPOSAL_INACTIVE');
    const review = JSON.parse(proposal.row.review);
    const concern = this.#db.prepare('SELECT * FROM concerns WHERE target_key=?').get(proposal.row.target_key);
    if (concern && (concern.state !== 'REASSESSED' || concern.selected_proposal !== proposal.row.id || concern.selected_digest !== proposal.row.digest)) deny('REVIEW_PENDING');
    if (!['NOT_REQUIRED', 'APPROVED', 'OWNER_RESOLVED'].includes(review.state)) deny('REVIEW_PENDING');
  }
  #releaseView(handle, body, proposalDigest, supersedes = null) {
    const output = detached({ proposalId: body.id, digest: proposalDigest, action: body.action, calendarId: body.calendarId,
      calendarName: body.calendarName, eventId: body.eventId, before: body.before, after: body.after,
      changedFields: body.changedFields, timeZone: body.after.timeZone, supersedes,
      notice: 'Geen melding aan anderen. Akkoord voor deze ene exacte wijziging.', execution: 'BLOCKED' });
    this.#sync(this.#beforeRelease, 'proposal');
    this.#authorize(handle, { calendarId: body.calendarId, purpose: body.purpose, fields: FIELDS, bound: body.grant, context: body.context });
    return output;
  }
  registerOwnCalendar(handle, input) {
    exact(input, ['calendarId', 'name']);
    const frame = this.#frame(handle);
    if (frame.c.actor !== 'OWNER') deny('OWNER_REQUIRED');
    if (typeof input.name !== 'string' || !input.name.trim() || input.name.length > 160) deny('INVALID_INPUT');
    return this.#tx(() => {
      const { c } = this.#frame(handle, frame.c); this.#observe();
      const body = { id: id(input.calendarId), name: input.name, owner: c.subject, scope: scope(c), shared: false, writeAcl: true, bindingRevision: 1 };
      this.#db.prepare('INSERT INTO calendars(id,scope,body) VALUES (?,?,?)').run(body.id, body.scope, canonical(body));
      return detached(body);
    });
  }
  issueGrant(handle, input) {
    exact(input, ['calendarId', 'purpose', 'recipients', 'fields', 'receiptRecipients', 'actions', 'expiresAt', 'reviewAllowed'], ['calendarId', 'purpose', 'recipients', 'fields', 'receiptRecipients', 'actions', 'expiresAt']);
    const frame = this.#frame(handle);
    if (frame.c.actor !== 'OWNER') deny('OWNER_REQUIRED');
    for (const [name, allowed] of [['recipients', ROLES], ['receiptRecipients', ROLES], ['fields', FIELDS], ['actions', Object.keys(ACTIONS)]]) {
      if (!Array.isArray(input[name]) || input[name].some(v => !allowed.includes(v)) || new Set(input[name]).size !== input[name].length) deny('INVALID_GRANT');
    }
    if (input.receiptRecipients.some(x => !input.recipients.includes(x)) || (input.reviewAllowed !== undefined && typeof input.reviewAllowed !== 'boolean')) deny('INVALID_GRANT');
    id(input.purpose);
    return this.#tx(() => {
      const { c, p } = this.#frame(handle, frame.c), cal = this.#calendar(c, input.calendarId), now = this.#observe();
      if (!Number.isSafeInteger(input.expiresAt) || input.expiresAt <= now || input.expiresAt - now > 86400000) deny('INVALID_EXPIRY');
      const rev = this.#db.prepare('SELECT COALESCE(MAX(revision),0)+1 AS n FROM grants WHERE calendar_id=?').get(cal.id).n;
      this.#db.prepare("UPDATE grants SET state='REVOKED' WHERE calendar_id=? AND state='ACTIVE'").run(cal.id);
      const g = detached({ ...input, id: randomUUID(), revision: rev, session: session(c), bindingRevision: cal.bindingRevision, policyVersion: p.version, reviewAllowed: input.reviewAllowed === true });
      this.#db.prepare("INSERT INTO grants(id,calendar_id,revision,state,body) VALUES (?,?,?,'ACTIVE',?)").run(g.id, cal.id, rev, canonical(g));
      return g;
    });
  }
  revoke(handle, input) {
    exact(input, ['calendarId', 'grantId']);
    const frame = this.#frame(handle);
    if (frame.c.actor !== 'OWNER') deny('OWNER_REQUIRED');
    return this.#tx(() => {
      this.#frame(handle, frame.c); this.#calendar(frame.c, input.calendarId); this.#observe();
      this.#db.prepare("UPDATE grants SET state='REVOKED' WHERE id=? AND calendar_id=? AND state='ACTIVE'").run(id(input.grantId), input.calendarId);
      this.#db.prepare('DELETE FROM approvals WHERE proposal_id IN (SELECT id FROM proposals WHERE json_extract(body,?)=?) AND consumed=0').run('$.grant.id', input.grantId);
      return detached({ status: 'REVOKED' });
    });
  }
  prepare(handle, input) { return this.#prepare(handle, input, null); }
  #prepare(handle, input, supersedes) {
    exact(input, ['requestRef', 'idempotencyKey', 'calendarId', 'purpose', 'action', 'eventId', 'expectedRevision', 'changes', 'origin'], ['requestRef', 'idempotencyKey', 'calendarId', 'purpose', 'action', 'changes', 'origin']);
    id(input.requestRef); id(input.idempotencyKey); id(input.purpose);
    if (!Object.hasOwn(ACTIONS, input.action)) deny('INVALID_ACTION');
    if (!['OWNER_DIRECT', 'HARA'].includes(input.origin)) deny('INVALID_ORIGIN');
    const a = this.#authorize(handle, { calendarId: input.calendarId, purpose: input.purpose, fields: FIELDS });
    if (!['OWNER', 'HANNIE'].includes(a.c.actor)) deny('PREPARE_ROLE_DENIED');
    // Until a host-mediated OWNER-instruction contract is bound, caller origin flags cannot waive review.
    if (input.origin === 'OWNER_DIRECT' && a.c.actor !== 'OWNER') deny('OWNER_INSTRUCTION_REQUIRED');
    let before = null;
    if (input.action === 'CREATE_OWN_EVENT') {
      if ('eventId' in input || 'expectedRevision' in input) deny('INVALID_INPUT');
    } else {
      if (!Number.isSafeInteger(input.expectedRevision) || input.expectedRevision < 1) deny('INVALID_REVISION');
      const e = this.#event(input.calendarId, input.eventId);
      if (e.revision !== input.expectedRevision) deny('REVISION_CONFLICT');
      before = e.snapshot;
    }
    const after = normalize(input.action, input.changes, before), contextKey = digest(a.c);
    const fingerprint = digest({ input, before, after, grant: { id: a.g.id, revision: a.g.revision }, binding: a.cal.bindingRevision, context: a.c, supersedes });
    const body = this.#tx(() => {
      this.#authorize(handle, { calendarId: input.calendarId, purpose: input.purpose, fields: FIELDS, bound: a.g, context: a.c });
      const old = this.#db.prepare('SELECT * FROM proposals WHERE context_key=? AND (request_ref=? OR idem_key=?)').all(contextKey, input.requestRef, input.idempotencyKey);
      if (old.length) {
        const b = JSON.parse(old[0].body);
        if (old.length !== 1 || b.fingerprint !== fingerprint || old[0].state === 'SUPERSEDED') deny('IDEMPOTENCY_CONFLICT');
        return b;
      }
      const b = detached({ id: randomUUID(), context: a.c, calendarId: input.calendarId, calendarName: a.cal.name, bindingRevision: a.cal.bindingRevision,
        purpose: input.purpose, requestRef: input.requestRef, idempotencyKey: input.idempotencyKey, action: input.action,
        eventId: input.eventId || randomUUID(), expectedRevision: input.expectedRevision || 0, before, after,
        changedFields: Object.keys(input.changes).sort(), grant: { id: a.g.id, revision: a.g.revision }, policyVersion: a.p.version,
        origin: input.origin, supersedes, fingerprint });
      this.#source(b);
      const target = scope(a.c) + '/' + input.calendarId + '/' + (input.action === 'CREATE_OWN_EVENT' ? '__CREATE__' : b.eventId);
      const review = { state: input.origin === 'OWNER_DIRECT' ? 'NOT_REQUIRED' : 'PENDING' };
      this.#db.prepare("INSERT INTO proposals(id,context_key,request_ref,idem_key,target_key,state,digest,body,review) VALUES (?,?,?,?,?,'PROPOSED',?,?,?)")
        .run(b.id, contextKey, input.requestRef, input.idempotencyKey, target, digest(b), canonical(b), canonical(review));
      return b;
    });
    return this.#releaseView(handle, body, digest(body), supersedes);
  }
  revise(handle, input) {
    exact(input, ['proposalId', 'digest', 'replacement']);
    const old = this.#proposal(handle, input.proposalId, input.digest);
    if (!['HANNIE', 'OWNER'].includes(old.frame.c.actor)) deny('PREPARE_ROLE_DENIED');
    const n = input.replacement;
    if (n.calendarId !== old.body.calendarId || n.action !== old.body.action ||
        (old.body.action !== 'CREATE_OWN_EVENT' && n.eventId !== old.body.eventId) ||
        n.requestRef === old.body.requestRef || n.idempotencyKey === old.body.idempotencyKey) deny('REVISION_TARGET_CHANGED');
    this.#authorize(handle, { calendarId: old.body.calendarId, purpose: old.body.purpose, fields: FIELDS, context: old.frame.c });
    this.#tx(() => {
      const fresh = this.#proposal(handle, input.proposalId, input.digest);
      if (!['PROPOSED', 'READY'].includes(fresh.row.state)) deny('PROPOSAL_INACTIVE');
      this.#db.prepare("UPDATE proposals SET state='SUPERSEDED' WHERE id=?").run(fresh.row.id);
      this.#db.prepare('DELETE FROM approvals WHERE proposal_id=? AND consumed=0').run(fresh.row.id);
    });
    // Intentional two checkpoints: failure of the successor must not resurrect the old approval.
    return this.#prepare(handle, n, old.row.id);
  }
  recordReview(handle, input) {
    exact(input, ['proposalId', 'digest', 'total', 'yes', 'concern', 'reassess', 'expectedConcernRevision'], ['proposalId', 'digest', 'total', 'yes', 'concern']);
    if (!Number.isSafeInteger(input.total) || !Object.hasOwn(THRESHOLDS, input.total) || !Number.isSafeInteger(input.yes) || input.yes < 0 || input.yes > input.total || typeof input.concern !== 'boolean') deny('INVALID_REVIEW');
    return this.#tx(() => {
      const p = this.#proposal(handle, input.proposalId, input.digest);
      this.#authorize(handle, { calendarId: p.body.calendarId, purpose: p.body.purpose, mode: 'review', context: p.frame.c });
      if (!['PROPOSED', 'READY'].includes(p.row.state)) deny('PROPOSAL_INACTIVE');
      const previous = this.#db.prepare('SELECT * FROM concerns WHERE target_key=?').get(p.row.target_key);
      let revision = previous?.revision || 0;
      if (input.concern) {
        revision++;
        this.#db.prepare("INSERT INTO concerns(target_key,revision,state) VALUES (?,?,'OPEN') ON CONFLICT(target_key) DO UPDATE SET revision=excluded.revision,state='OPEN',selected_proposal=NULL,selected_digest=NULL").run(p.row.target_key, revision);
        this.#db.prepare('DELETE FROM approvals WHERE consumed=0 AND proposal_id IN (SELECT id FROM proposals WHERE target_key=?)').run(p.row.target_key);
      } else if (previous) {
        if (input.reassess !== true || input.expectedConcernRevision !== revision || input.yes < THRESHOLDS[input.total]) deny('REVIEW_PENDING');
        this.#db.prepare("UPDATE concerns SET state='REASSESSED',selected_proposal=?,selected_digest=? WHERE target_key=?").run(p.row.id, p.row.digest, p.row.target_key);
        this.#db.prepare('DELETE FROM approvals WHERE consumed=0 AND proposal_id IN (SELECT id FROM proposals WHERE target_key=?)').run(p.row.target_key);
      }
      const review = { state: input.concern ? 'PENDING' : input.yes >= THRESHOLDS[input.total] ? 'APPROVED' : 'DISSENT',
        total: input.total, yes: input.yes, dissent: input.total - input.yes, concernRevision: revision };
      this.#db.prepare('UPDATE proposals SET review=? WHERE id=?').run(canonical(review), p.row.id);
      this.#db.prepare('DELETE FROM approvals WHERE proposal_id=? AND consumed=0').run(p.row.id);
      this.#db.prepare('INSERT INTO review_history(proposal_id,body) VALUES (?,?)').run(p.row.id, canonical({ ...review, proposalDigest: p.row.digest, reviewerContext: p.frame.c }));
      return detached(review);
    });
  }
  resolveInternalConflict(handle, input) {
    exact(input, ['proposalId', 'digest']);
    return this.#tx(() => {
      const p = this.#proposal(handle, input.proposalId, input.digest);
      if (p.frame.c.actor !== 'OWNER') deny('OWNER_REQUIRED');
      this.#authorize(handle, { calendarId: p.body.calendarId, purpose: p.body.purpose, bound: p.body.grant, recipient: p.body.context.actor, context: p.frame.c });
      if (!['PROPOSED', 'READY'].includes(p.row.state)) deny('PROPOSAL_INACTIVE');
      if (this.#db.prepare('SELECT 1 FROM concerns WHERE target_key=?').get(p.row.target_key)) deny('REVIEW_PENDING');
      const review = JSON.parse(p.row.review);
      if (review.state !== 'DISSENT') deny('REVIEW_PENDING');
      this.#db.prepare('UPDATE proposals SET review=? WHERE id=?').run(canonical({ ...review, state: 'OWNER_RESOLVED' }), p.row.id);
      this.#db.prepare('INSERT INTO review_history(proposal_id,body) VALUES (?,?)').run(p.row.id, canonical({ ...review, state: 'OWNER_RESOLVED', proposalDigest: p.row.digest, ownerContext: p.frame.c }));
      this.#db.prepare('DELETE FROM approvals WHERE proposal_id=? AND consumed=0').run(p.row.id);
      return detached({ status: 'OWNER_RESOLVED', writeAuthority: false });
    });
  }
  confirm(handle, input) {
    exact(input, ['proposalId', 'digest']);
    const initial = this.#proposal(handle, input.proposalId, input.digest);
    if (initial.frame.c.actor !== 'OWNER') deny('OWNER_REQUIRED');
    const result = this.#tx(() => {
      const p = this.#proposal(handle, input.proposalId, input.digest);
      const a = this.#authorize(handle, { calendarId: p.body.calendarId, purpose: p.body.purpose, mode: 'write',
        action: p.body.action, bound: p.body.grant, recipient: p.body.context.actor, context: initial.frame.c });
      this.#source(p.body); this.#ready(p);
      const old = this.#db.prepare('SELECT * FROM approvals WHERE proposal_id=?').get(p.row.id);
      if (old && !old.consumed) {
        const b = JSON.parse(old.body);
        if (b.expiresAt > a.now) return b;
        this.#db.prepare('DELETE FROM approvals WHERE id=? AND consumed=0').run(old.id);
      }
      const approval = detached({ id: randomUUID(), proposalId: p.row.id, proposalDigest: p.row.digest,
        grantId: a.g.id, grantRevision: a.g.revision, policyVersion: a.p.version, bindingRevision: a.cal.bindingRevision,
        ownerSession: session(a.c), issuedAt: a.now, expiresAt: Math.min(a.now + 300000, a.g.expiresAt) });
      this.#db.prepare('INSERT INTO approvals(id,proposal_id,body) VALUES (?,?,?)').run(approval.id, p.row.id, canonical(approval));
      this.#db.prepare("UPDATE proposals SET state='READY' WHERE id=?").run(p.row.id);
      this.#authorize(handle, { calendarId: p.body.calendarId, purpose: p.body.purpose, mode: 'write',
        action: p.body.action, bound: p.body.grant, recipient: p.body.context.actor, context: initial.frame.c });
      return approval;
    });
    const post = this.#authorize(handle, { calendarId: initial.body.calendarId, purpose: initial.body.purpose, mode: 'write',
      action: initial.body.action, bound: initial.body.grant, recipient: initial.body.context.actor, context: initial.frame.c });
    if (post.now >= result.expiresAt) deny('APPROVAL_EXPIRED');
    return detached({ approvalId: result.id, proposalId: result.proposalId, digest: result.proposalDigest, expiresAt: result.expiresAt, execution: 'BLOCKED' });
  }
  readEvent(handle, input) {
    exact(input, ['calendarId', 'eventId', 'purpose']);
    const a = this.#authorize(handle, { calendarId: input.calendarId, purpose: input.purpose });
    const e = this.#event(input.calendarId, input.eventId);
    const projected = detached(Object.fromEntries(a.g.fields.map(f => [f, e.snapshot[f]])));
    const output = detached({ eventId: e.id, revision: e.revision, event: projected });
    this.#sync(this.#beforeRelease, 'readEvent');
    this.#authorize(handle, { calendarId: input.calendarId, purpose: input.purpose, bound: a.g, fields: a.g.fields, context: a.c });
    if (!a.g.fields.length) deny('FIELD_DENIED');
    return output;
  }
  #receipt(p) {
    const row = this.#db.prepare('SELECT * FROM receipts WHERE proposal_id=?').get(p.row.id);
    if (!row || p.row.state !== 'COMMITTED') deny('RECEIPT_UNAVAILABLE');
    const r = JSON.parse(row.body), b = p.body;
    const v = this.#db.prepare('SELECT * FROM event_versions WHERE event_id=? AND revision=?').get(r.eventId, r.eventRevision);
    const a = this.#db.prepare('SELECT * FROM mutation_audit WHERE seq=?').get(r.auditSequence);
    const approval = this.#db.prepare('SELECT * FROM approvals WHERE id=? AND proposal_id=?').get(r.approvalId, b.id);
    const historicalGrant = this.#db.prepare('SELECT * FROM grants WHERE id=?').get(b.grant.id);
    const e = this.#event(b.calendarId, b.eventId);
    if (!v || !a || !approval || !approval.consumed || !historicalGrant) deny('RECEIPT_BINDING_MISMATCH');
    const ap = JSON.parse(approval.body), audit = JSON.parse(a.body), snapshot = JSON.parse(v.snapshot);
    const hg = JSON.parse(historicalGrant.body);
    const current = this.#db.prepare('SELECT * FROM event_versions WHERE event_id=? AND revision=?').get(e.id, e.revision);
    const expected = { id: row.id, proposalId: b.id, proposalDigest: p.row.digest, contextDigest: digest(b.context),
      requestRef: b.requestRef, idempotencyKey: b.idempotencyKey, calendarId: b.calendarId, eventId: b.eventId,
      eventRevision: b.expectedRevision + 1, grantId: b.grant.id, grantRevision: b.grant.revision,
      policyVersion: b.policyVersion, bindingRevision: b.bindingRevision, snapshotDigest: digest(b.after),
      approvalId: approval.id, auditSequence: a.seq, operationId: a.operation_id };
    if (!same(r, expected) || !same(snapshot, b.after) || v.digest !== digest(snapshot) ||
        !current || current.digest !== digest(e.snapshot) || !same(JSON.parse(current.snapshot), e.snapshot) ||
        e.revision < r.eventRevision || historicalGrant.revision !== b.grant.revision ||
        ap.proposalId !== b.id || ap.proposalDigest !== p.row.digest || ap.grantId !== b.grant.id ||
        ap.grantRevision !== b.grant.revision || ap.ownerSession !== session(b.context) ||
        ap.policyVersion !== b.policyVersion || ap.bindingRevision !== b.bindingRevision ||
        !Number.isSafeInteger(ap.issuedAt) || !Number.isSafeInteger(ap.expiresAt) ||
        ap.expiresAt <= ap.issuedAt || ap.expiresAt > Math.min(ap.issuedAt + 300000, hg.expiresAt) ||
        !same(audit, { ...expected, id: row.id })) deny('RECEIPT_BINDING_MISMATCH');
    // Audit content is strictly binding metadata; the event snapshot never enters its payload.
    return { r: detached(r), snapshot: detached(snapshot), currentRevision: e.revision };
  }
  #ownerReceiptMetadata(handle, p, recovered) {
    const first = this.#frame(handle, p.frame.c);
    this.#calendar(first.c, p.body.calendarId); this.#observe();
    const final = this.#frame(handle, first.c);
    if (!same(first.p, final.p)) deny('POLICY_CHANGED');
    this.#calendar(final.c, p.body.calendarId);
    const now = this.#sample();
    if (now < this.#highest) deny('TEMPORAL_UNCERTAIN');
    this.#highest = now;
    return detached({ status: 'COMMITTED_RESULT_WITHHELD', receiptId: recovered.r.id, operationId: recovered.r.operationId, historicalRevision: recovered.r.eventRevision });
  }
  recover(handle, input) {
    exact(input, ['proposalId', 'digest']);
    try {
      const p = this.#proposal(handle, input.proposalId, input.digest);
      if (p.frame.c.actor !== 'OWNER') {
        this.#authorize(handle, { calendarId: p.body.calendarId, purpose: p.body.purpose, mode: 'receipt', context: p.frame.c });
      }
      let recovered = this.#receipt(p);
      // Snapshot projection precedes the final release fence. No external calls follow that fence.
      let initial = null;
      try { initial = this.#authorize(handle, { calendarId: p.body.calendarId, purpose: p.body.purpose, mode: 'receipt', context: p.frame.c }); }
      catch (e) {
        if (p.frame.c.actor !== 'OWNER' || !(e instanceof CalendarError) ||
            !['CONSENT_INACTIVE', 'GRANT_BINDING_CHANGED', 'RECIPIENT_DENIED', 'PURPOSE_DENIED', 'RECEIPT_ACCESS_DENIED'].includes(e.code)) throw e;
      }
      const payload = initial ? detached(Object.fromEntries(initial.g.fields.map(f => [f, recovered.snapshot[f]]))) : null;
      this.#sync(this.#beforeRelease, 'recover');
      recovered = this.#receipt(this.#proposal(handle, input.proposalId, input.digest));
      if (!initial) {
        // Narrow same-session OWNER receipt exception: metadata only, no event identity or payload.
        return this.#ownerReceiptMetadata(handle, p, recovered);
      }
      let final;
      try {
        final = this.#authorize(handle, { calendarId: p.body.calendarId, purpose: p.body.purpose, mode: 'receipt',
          bound: initial.g, fields: initial.g.fields, context: p.frame.c });
      } catch (e) {
        if (p.frame.c.actor !== 'OWNER' || !(e instanceof CalendarError) ||
            !['CONSENT_INACTIVE', 'GRANT_BINDING_CHANGED', 'RECIPIENT_DENIED', 'PURPOSE_DENIED', 'RECEIPT_ACCESS_DENIED'].includes(e.code)) throw e;
        return this.#ownerReceiptMetadata(handle, p, recovered);
      }
      if (!final.g.fields.length) return detached({ status: 'COMMITTED_RESULT_WITHHELD', receiptId: recovered.r.id, operationId: recovered.r.operationId });
      return detached({ status: 'SUCCEEDED', receiptId: recovered.r.id, operationId: recovered.r.operationId,
        historical: recovered.currentRevision !== recovered.r.eventRevision, eventRevision: recovered.r.eventRevision,
        currentRevision: recovered.currentRevision, event: payload });
    } catch (e) {
      return unknown(e instanceof CalendarError ? e.code : 'RECOVERY_READ_FAILED');
    }
  }
  status() {
    return detached({ candidate: VERSION, contract: 'HARA-AGENDA-v0.3 / D-012', schema: 'D012-1',
      actions: Object.keys(ACTIONS), execution: 'BLOCKED', executionCode: 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED',
      effectDeadlineCapability: 'UNPROVEN', AM_R01: 'OPEN', D010: 'OPEN', integration: 'HOLD', production: 'HOLD',
      independentReview: 'PENDING', hostedD1: 'NOT EXECUTED', AM10: 'NOT EXECUTED', proof: 'UNVERIFIED' });
  }
  close() { this.#db.close(); }
}

Object.defineProperty(PalacoCalendarAdapter.prototype, 'execute', { value: mutationDeny, writable: false, configurable: false });
Object.freeze(PalacoCalendarAdapter.prototype);
Object.freeze(PalacoCalendarAdapter);
