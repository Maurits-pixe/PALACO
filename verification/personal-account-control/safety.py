"""Synthetic independent deny store. Every served access must use GuardedModel.

Separate SQLite files are not separate failure domains. No production runtime is
wired to this fixture. There is deliberately no reset/unblock runtime operation.
"""
from pathlib import Path
import sqlite3
from model import Denied


class SafetyStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.failed = False
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=1)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS circuit (
          id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL
          CHECK(state IN ('UNPROVISIONED','OPEN','LOCKED')));
        INSERT OR IGNORE INTO circuit VALUES(1,'UNPROVISIONED');
        CREATE TABLE IF NOT EXISTS denied_account (
          account TEXT PRIMARY KEY, actor TEXT NOT NULL, occurred INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS incident (
          sequence INTEGER PRIMARY KEY, reason TEXT NOT NULL,
          account TEXT, actor TEXT, occurred INTEGER NOT NULL);
        CREATE TRIGGER IF NOT EXISTS preserve_incident_update BEFORE UPDATE ON incident
          BEGIN SELECT RAISE(ABORT,'immutable safety evidence'); END;
        CREATE TRIGGER IF NOT EXISTS preserve_incident_delete BEFORE DELETE ON incident
          BEGIN SELECT RAISE(ABORT,'immutable safety evidence'); END;
        CREATE TRIGGER IF NOT EXISTS preserve_deny_update BEFORE UPDATE ON denied_account
          BEGIN SELECT RAISE(ABORT,'immutable deny intent'); END;
        CREATE TRIGGER IF NOT EXISTS preserve_deny_delete BEFORE DELETE ON denied_account
          BEGIN SELECT RAISE(ABORT,'immutable deny intent'); END;
        ''')

    def fixture_provision_once(self):
        """Explicit local fixture setup only. Cannot unlock a tripped store."""
        try:
            self.db.execute('BEGIN IMMEDIATE')
            state=self.db.execute('SELECT state FROM circuit WHERE id=1').fetchone()
            count=self.db.execute('SELECT COUNT(*) FROM incident').fetchone()[0]
            if state is None or state[0]!='UNPROVISIONED' or count:
                raise Denied('SAFETY_PROVISION_REFUSED')
            self.db.execute("UPDATE circuit SET state='OPEN' WHERE id=1")
            self.db.execute("INSERT INTO incident VALUES(NULL,'FIXTURE_PROVISIONED',NULL,NULL,0)")
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise

    def run(self, account, now, action, *, actor=None, suspend_intent=False):
        """Serialize guards; all access requires writable safety storage.

        For suspension, persist deny intent before attempting the primary write.
        Primary exceptions trip the global circuit. Safety failure denies locally.
        """
        if self.failed:
            raise Denied('SAFETY_UNAVAILABLE')
        primary_failed=False
        try:
            self.db.execute('BEGIN IMMEDIATE')
            state=self.db.execute('SELECT state FROM circuit WHERE id=1').fetchone()
            if state is None or state[0]!='OPEN':
                raise Denied('SAFETY_CIRCUIT_CLOSED')
            blocked=self.db.execute('SELECT 1 FROM denied_account WHERE account=?',(account,)).fetchone()
            if blocked and not suspend_intent:
                raise Denied('SAFETY_ACCOUNT_BLOCKED')
            if suspend_intent:
                self.db.execute('INSERT OR IGNORE INTO denied_account VALUES(?,?,?)',(account,actor,now))
                if not blocked:
                    self.db.execute("INSERT INTO incident VALUES(NULL,'SUSPENSION_INTENT',?,?,?)",
                                    (account,actor,now))
                # Crash after this commit must not lose the deny intent.
                self.db.execute('COMMIT')
                self.db.execute('BEGIN IMMEDIATE')
            try:
                result=action()
            except sqlite3.Error:
                primary_failed=True
                self.db.execute("UPDATE circuit SET state='LOCKED' WHERE id=1")
                self.db.execute("INSERT INTO incident VALUES(NULL,'PRIMARY_STORAGE_FAILURE',?,?,?)",
                                (account,actor,now))
            self.db.execute('COMMIT')
        except sqlite3.Error:
            self.failed=True
            try:
                if self.db.in_transaction: self.db.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            raise Denied('SAFETY_UNAVAILABLE') from None
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise
        if primary_failed:
            raise Denied('PRIMARY_STORAGE_FAILURE_SAFETY_LOCKED')
        return result


class GuardedModel:
    """Trusted local facade; bypassing it bypasses the safety contract."""
    def __init__(self, model, safety):
        primary=model.db.execute('PRAGMA database_list').fetchone()[2]
        if not primary or Path(primary).resolve()==safety.path:
            raise ValueError('distinct persistent database files required')
        # Hard links must not masquerade as independent files.
        if Path(primary).samefile(safety.path):
            raise ValueError('distinct database files required')
        self.model,self.safety=model,safety

    def allowed(self, account, workspace, now):
        try:
            return self.safety.run(account,now,lambda:self.model.allowed(account,workspace,now))
        except Denied:
            return False

    def activate(self, account, revision, now, until, key, **kwargs):
        return self.safety.run(account,now,
            lambda:self.model.activate(account,revision,now,until,key,**kwargs),
            actor=kwargs.get('actor','TST-activator'))

    def review(self, account, now, checklist, **kwargs):
        return self.safety.run(account,now,
            lambda:self.model.review(account,now,checklist,**kwargs),
            actor=kwargs.get('actor','TST-reviewer'))

    def suspend(self, account, now, actor='TST-support'):
        self.model.actor(actor,'suspend')
        # Check authority through the same guard. If storage is unavailable,
        # global deny is safe; no personal authority is inferred from the error.
        def authorize():
            row=self.model.get(account)
            self.model.mandate(actor,'suspend',row['workspace'],row['scope'],now)
        self.safety.run(account,now,authorize,actor=actor,suspend_intent=False)
        return self.safety.run(account,now,
            lambda:self.model.suspend(account,now,actor=actor),actor=actor,suspend_intent=True)
