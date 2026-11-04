"""Executable synthetic reference model. No identity provider or runtime authority.

Actors and evidence are fixture assertions, never authenticated human attestations.
SQLite is local test storage, not a production audit trust boundary.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager, nullcontext


class Denied(ValueError):
    pass


class Model:
    def __init__(self, path=':memory:'):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS account (
          id TEXT PRIMARY KEY, workspace TEXT, scope TEXT, state TEXT,
          revision INTEGER, inviter TEXT, reviewer TEXT, reviewed INTEGER,
          expires INTEGER, token TEXT, invite_until INTEGER, used INTEGER);
        CREATE TABLE IF NOT EXISTS audit (
          sequence INTEGER PRIMARY KEY, account TEXT, actor TEXT,
          event TEXT, previous TEXT, current TEXT, at INTEGER);
        CREATE TRIGGER IF NOT EXISTS no_audit_update BEFORE UPDATE ON audit
          BEGIN SELECT RAISE(ABORT, 'append only'); END;
        CREATE TRIGGER IF NOT EXISTS no_audit_delete BEFORE DELETE ON audit
          BEGIN SELECT RAISE(ABORT, 'append only'); END;
        CREATE TABLE IF NOT EXISTS mandate (
          actor TEXT, role TEXT, workspace TEXT, scope TEXT, until INTEGER,
          revoked INTEGER DEFAULT 0, PRIMARY KEY(actor,role));
        CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, version TEXT);
        INSERT OR IGNORE INTO policy VALUES(1,'staging-v1');
        CREATE TABLE IF NOT EXISTS review_evidence (
          account TEXT PRIMARY KEY, revision INTEGER, reviewer TEXT,
          workspace TEXT, scope TEXT, policy TEXT, until INTEGER, reference TEXT);
        CREATE TABLE IF NOT EXISTS suspension_outbox (
          id INTEGER PRIMARY KEY, account TEXT NOT NULL, actor TEXT NOT NULL,
          previous TEXT NOT NULL, current TEXT NOT NULL CHECK(current='SUSPENDED'),
          occurred INTEGER NOT NULL, audit_sequence INTEGER);
        CREATE TRIGGER IF NOT EXISTS no_outbox_delete BEFORE DELETE ON suspension_outbox
          BEGIN SELECT RAISE(ABORT, 'preserve suspension evidence'); END;
        CREATE TRIGGER IF NOT EXISTS no_outbox_payload_update
          BEFORE UPDATE OF id,account,actor,previous,current,occurred ON suspension_outbox
          BEGIN SELECT RAISE(ABORT, 'immutable suspension evidence'); END;
        CREATE TRIGGER IF NOT EXISTS no_outbox_redelivery
          BEFORE UPDATE OF audit_sequence ON suspension_outbox
          WHEN OLD.audit_sequence IS NOT NULL OR NEW.audit_sequence IS NULL
          BEGIN SELECT RAISE(ABORT, 'immutable delivery receipt'); END;
        CREATE TABLE IF NOT EXISTS request (
          key TEXT PRIMARY KEY, payload TEXT);
        ''')
        self.db.row_factory = sqlite3.Row
        self.roles = {'TST-inviter': 'invite', 'TST-reviewer': 'review',
                      'TST-activator': 'activate', 'TST-support': 'suspend'}

    @contextmanager
    def transaction(self, finalize=None):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            with finalize() if finalize else nullcontext():
                self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    def seed_fixture_mandates(self, until=100):
        """Explicit synthetic fixture setup, not an authority provisioning API."""
        with self.transaction():
            for actor, role in self.roles.items():
                self.db.execute('INSERT INTO mandate VALUES(?,?,?,?,?,0)',
                                (actor, role, 'synthetic', 'synthetic:read', until))

    def mandate(self, actor, role, workspace, scope, now):
        self.actor(actor, role)
        row = self.db.execute('SELECT * FROM mandate WHERE actor=? AND role=?',
                              (actor, role)).fetchone()
        if (row is None or row['revoked'] or row['until'] <= now
            or row['workspace'] != workspace or row['scope'] != scope):
            raise Denied('MANDATE_INVALID')

    def actor(self, actor, role):
        if self.roles.get(actor) != role:
            raise Denied('ACTOR_NOT_AUTHORIZED')

    def get(self, account):
        row = self.db.execute('SELECT * FROM account WHERE id=?', (account,)).fetchone()
        if row is None:
            raise Denied('UNKNOWN_ACCOUNT')
        return row

    def check_binding(self, row, expected):
        """Called under the write lock: do not approve a stale intake payload."""
        if expected is None:
            return  # Direct fixture model API retains its original test contract.
        policy = self.db.execute('SELECT version FROM policy WHERE id=1').fetchone()
        actual = {'revision': row['revision'], 'workspace': row['workspace'],
                  'scope': row['scope'], 'policy': policy[0] if policy else None}
        if expected != actual:
            raise Denied('STALE_INTAKE_BINDING')

    def event(self, account, actor, event, old, new, now):
        cursor = self.db.execute('INSERT INTO audit VALUES(NULL,?,?,?,?,?,?)',
                        (account, actor, event, old, new, now))
        return cursor.lastrowid

    def transition(self, account, actor, old, new, now):
        if self.get(account)['state'] != old:
            raise Denied('INVALID_TRANSITION')
        self.db.execute('UPDATE account SET state=? WHERE id=?', (new, account))
        self.event(account, actor, 'state.changed', old, new, now)

    def invite(self, account, token, now, until, actor='TST-inviter'):
        self.actor(actor, 'invite')
        if not account.startswith('TST-') or not token or until <= now:
            raise Denied('SYNTHETIC_INVITATION_REQUIRED')
        with self.transaction():
            self.mandate(actor, 'invite', 'synthetic', 'synthetic:read', now)
            self.db.execute('INSERT INTO account VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (account, 'synthetic', 'synthetic:read', 'INVITED', 1, actor,
                 None, None, None, hashlib.sha256(token.encode()).hexdigest(), until, 0))
            self.event(account, actor, 'invitation.issued', None, 'INVITED', now)

    def verify(self, account, token, now, recipient):
        with self.transaction():
            row = self.get(account)
            if (recipient != account or row['used'] or row['invite_until'] <= now
                or row['token'] != hashlib.sha256(token.encode()).hexdigest()):
                raise Denied('INVITATION_INVALID')
            self.transition(account, recipient, 'INVITED', 'INVITATION_VERIFIED', now)
            self.db.execute('UPDATE account SET used=1 WHERE id=?', (account,))

    def stage(self, account, now):
        with self.transaction():
            self.transition(account, 'fixture', 'INVITATION_VERIFIED', 'ACCOUNT_STAGED', now)
            self.transition(account, 'fixture', 'ACCOUNT_STAGED', 'SAFETY_REVIEW_PENDING', now)

    def review(self, account, now, checklist, actor='TST-reviewer', *, valid_until=50, evidence_ref='EVD-SYNTHETIC-REVIEW', expected_binding=None, commit_guard=None):
        self.actor(actor, 'review')
        required = {'purpose', 'scope', 'privacy', 'risk', 'escalation', 'recovery',
                    'clinical_boundary', 'human_owner', 'consent_basis'}
        if set(checklist) != required or any(v is not True for v in checklist.values()):
            raise Denied('INCOMPLETE_REVIEW')
        @contextmanager
        def finalize():
            with commit_guard() if commit_guard else nullcontext(now) as current:
                if type(current) is not int or current < now or valid_until <= current:
                    raise Denied('COMMIT_TIME_INVALID')
                row = self.get(account)
                self.check_binding(row, expected_binding)
                self.mandate(actor, 'review', row['workspace'], row['scope'], current)
                yield
        with self.transaction(finalize):
            row = self.get(account)
            self.check_binding(row, expected_binding)
            self.mandate(actor, 'review', row['workspace'], row['scope'], now)
            if valid_until <= now or not evidence_ref.startswith('EVD-SYNTHETIC-'):
                raise Denied('REVIEW_EVIDENCE_INVALID')
            if actor == row['inviter']:
                raise Denied('SEPARATION_REQUIRED')
            self.transition(account, actor, 'SAFETY_REVIEW_PENDING', 'APPROVED_FOR_ACTIVATION', now)
            self.db.execute('UPDATE account SET reviewer=?, reviewed=revision WHERE id=?',
                            (actor, account))
            policy = self.db.execute('SELECT version FROM policy WHERE id=1').fetchone()[0]
            self.db.execute('INSERT OR REPLACE INTO review_evidence VALUES(?,?,?,?,?,?,?,?)',
                (account, row['revision'], actor, row['workspace'], row['scope'],
                 policy, valid_until, evidence_ref))

    def change_scope(self, account, scope, now, actor='TST-inviter'):
        self.actor(actor, 'invite')
        with self.transaction():
            row = self.get(account)
            self.mandate(actor, 'invite', row['workspace'], row['scope'], now)
            if row['state'] not in {'SAFETY_REVIEW_PENDING', 'APPROVED_FOR_ACTIVATION'}:
                raise Denied('INVALID_TRANSITION')
            self.db.execute('UPDATE account SET scope=?, revision=revision+1, reviewed=NULL, '
                            'state=? WHERE id=?', (scope, 'SAFETY_REVIEW_PENDING', account))
            self.event(account, actor, 'review.invalidated', row['state'], 'SAFETY_REVIEW_PENDING', now)

    def activate(self, account, revision, now, until, key, actor='TST-activator', environment='staging', *, expected_binding=None, commit_guard=None):
        if environment != 'staging':
            raise Denied('PRODUCTION_ACTIVATION_BLOCKED')
        self.actor(actor, 'activate')
        payload = json.dumps([account, revision, until, actor, environment])
        @contextmanager
        def finalize():
            with commit_guard() if commit_guard else nullcontext(now) as current:
                if type(current) is not int or current < now or until <= current:
                    raise Denied('COMMIT_TIME_INVALID')
                row = self.get(account)
                self.check_binding(row, expected_binding)
                self.mandate(actor, 'activate', row['workspace'], row['scope'], current)
                evidence = self.db.execute('SELECT * FROM review_evidence WHERE account=?', (account,)).fetchone()
                if evidence is None or evidence['until'] <= current:
                    raise Denied('REVIEW_EVIDENCE_EXPIRED_AT_COMMIT')
                self.mandate(evidence['reviewer'], 'review', row['workspace'], row['scope'], current)
                yield
        with self.transaction(finalize):
            row = self.get(account)
            self.check_binding(row, expected_binding)
            self.mandate(actor, 'activate', row['workspace'], row['scope'], now)
            evidence = self.db.execute('SELECT * FROM review_evidence WHERE account=?', (account,)).fetchone()
            policy = self.db.execute('SELECT version FROM policy WHERE id=1').fetchone()[0]
            if (evidence is None or evidence['revision'] != revision
                or evidence['reviewer'] != row['reviewer'] or evidence['until'] <= now
                or evidence['policy'] != policy or evidence['workspace'] != row['workspace']
                or evidence['scope'] != row['scope']):
                raise Denied('REVIEW_EVIDENCE_INVALID')
            self.mandate(evidence['reviewer'], 'review', row['workspace'], row['scope'], now)
            if (row['revision'] != revision or row['reviewed'] != revision
                or row['workspace'] != 'synthetic' or row['scope'] != 'synthetic:read'
                or actor in {row['inviter'], row['reviewer']} or until <= now):
                raise Denied('ACTIVATION_EVIDENCE_INVALID')
            existing = self.db.execute('SELECT payload FROM request WHERE key=?', (key,)).fetchone()
            if existing:
                if existing['payload'] != payload or row['state'] != 'ACTIVE' or row['expires'] <= now:
                    raise Denied('REPLAY_CONFLICT_OR_REVOKED')
                return 'ACTIVE'
            self.transition(account, actor, 'APPROVED_FOR_ACTIVATION', 'ACTIVE', now)
            self.db.execute('UPDATE account SET expires=? WHERE id=?', (until, account))
            self.db.execute('INSERT INTO request VALUES(?,?)', (key, payload))
        return 'ACTIVE'

    def suspend(self, account, now, actor='TST-support'):
        """Commit access denial and recovery evidence BEFORE attempting audit delivery.

        AUDIT_PENDING is an explicit degraded outcome, never a completed audit claim.
        Failure to commit the block/outbox raises; it must not be reported as success.
        """
        self.actor(actor, 'suspend')
        with self.transaction():
            row = self.get(account)
            self.mandate(actor, 'suspend', row['workspace'], row['scope'], now)
            if row['state'] == 'SUSPENDED':
                previous = self.db.execute(
                    'SELECT id FROM suspension_outbox WHERE account=? ORDER BY id DESC LIMIT 1',
                    (account,)).fetchone()
                if previous is None:
                    raise Denied('SUSPENSION_EVIDENCE_MISSING')
                outbox_id = previous['id']
            else:
                if row['state'] not in {'ACTIVE', 'APPROVED_FOR_ACTIVATION', 'INVITED'}:
                    raise Denied('INVALID_TRANSITION')
                self.db.execute("UPDATE account SET state='SUSPENDED' WHERE id=?", (account,))
                cursor = self.db.execute(
                    'INSERT INTO suspension_outbox VALUES(NULL,?,?,?,?,?,NULL)',
                    (account, actor, row['state'], 'SUSPENDED', now))
                outbox_id = cursor.lastrowid
        return self.deliver_suspension(outbox_id)

    def deliver_suspension(self, outbox_id):
        """Trusted local recovery operation. Does not grant or restore any access."""
        try:
            with self.transaction():
                item = self.db.execute('SELECT * FROM suspension_outbox WHERE id=?',
                                       (outbox_id,)).fetchone()
                if item is None:
                    raise Denied('UNKNOWN_SUSPENSION')
                if item['audit_sequence'] is not None:
                    return 'AUDIT_DELIVERED'
                sequence = self.event(item['account'], item['actor'], 'account.suspended',
                                      item['previous'], item['current'], item['occurred'])
                self.db.execute('UPDATE suspension_outbox SET audit_sequence=? WHERE id=?',
                                (sequence, outbox_id))
            return 'AUDIT_DELIVERED'
        except sqlite3.Error:
            # The earlier transaction already durably committed access denial.
            return 'AUDIT_PENDING'

    def pending_suspensions(self):
        """Recovery queue; original actor/time remain in immutable payload columns."""
        return self.db.execute(
            'SELECT * FROM suspension_outbox WHERE audit_sequence IS NULL ORDER BY id').fetchall()

    def allowed(self, account, workspace, now):
        row = self.get(account)
        return (row['state'] == 'ACTIVE' and row['workspace'] == workspace
                and row['expires'] > now)

    def recover_authentication(self, account):
        # Model intentionally makes no lifecycle/permission change.
        return self.get(account)['state']
