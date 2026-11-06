"""Per-process synthetic startup fence. No real human approval or reset authority.

The trusted fixture supplies the actor-role map. Neither review nor approval is
exposed over HTTP. Existing global/account safety locks cannot be removed here.
"""
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import hashlib
import json
import os
import secrets
import sqlite3
from threading import RLock
from types import MappingProxyType

from model import Denied


@dataclass(frozen=True)
class BootReview:
    boot: str
    pid: int
    reviewer: str
    digest: str
    issued: int
    until: int


class RestartGuard:
    def __init__(self, guarded, clock, fixture_roles):
        self.guarded=guarded
        self.clock=clock
        self.roles=MappingProxyType(dict(fixture_roles))
        self.boot=secrets.token_hex(32)
        self.pid=os.getpid()
        self.failed=False
        self.last_time=None
        self.pending=None
        self.approved=None
        self.approver=None
        self.lock=RLock()

    def now(self):
        value=self.clock()
        if (os.getpid()!=self.pid or type(value) is not int or self.failed
            or (self.last_time is not None and value < self.last_time)):
            self.failed=True
            raise Denied('BOOT_FENCE_INVALID')
        self.last_time=value
        return value

    def authority(self, actor, role):
        if self.roles.get(actor)!=role:
            raise Denied('BOOT_AUTHORITY_REQUIRED')

    @contextmanager
    def snapshot(self):
        """Same lock order as the safety guard: safety, then primary."""
        safety=self.guarded.safety
        primary=self.guarded.model
        try:
            if safety.failed:
                raise Denied('SAFETY_UNAVAILABLE')
            safety.db.execute('BEGIN IMMEDIATE')
            primary.db.execute('BEGIN IMMEDIATE')
            for connection in (safety.db,primary.db):
                if [r[0] for r in connection.execute('PRAGMA quick_check')] != ['ok']:
                    raise Denied('STORAGE_CHECK_FAILED')
            state=safety.db.execute('SELECT state FROM circuit WHERE id=1').fetchone()
            if state is None or state[0]!='OPEN':
                raise Denied('SAFETY_RECOVERY_REQUIRED')
            if primary.pending_suspensions() or primary.pending_terminal_events():
                raise Denied('AUDIT_RECONCILIATION_REQUIRED')
            for row in safety.db.execute('SELECT account FROM denied_account'):
                if primary.get(row[0])['state'] not in {'SUSPENDED','REVOKED','EXPIRED'}:
                    raise Denied('ACCOUNT_RECONCILIATION_REQUIRED')
            yield safety,primary
            primary.db.execute('COMMIT')
            safety.db.execute('COMMIT')
        except sqlite3.Error:
            self.failed=True
            raise Denied('BOOT_STORAGE_UNAVAILABLE') from None
        finally:
            for connection in (primary.db,safety.db):
                try:
                    if connection.in_transaction: connection.execute('ROLLBACK')
                except sqlite3.Error:
                    pass

    def digest(self):
        data={}
        for prefix,connection,tables in (
            ('primary',self.guarded.model.db,('account','mandate','policy','review_evidence',
                                            'suspension_outbox','terminal_outbox','audit','request')),
            ('safety',self.guarded.safety.db,('circuit','denied_account','incident'))):
            for table in tables:
                rows=[tuple(row) for row in connection.execute(f'SELECT * FROM {table}')]
                data[prefix+'.'+table]=sorted(rows,key=lambda row:json.dumps(row))
        return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def review_boot(self, actor, *, valid_until):
        with self.lock:
            now=self.now()
            self.authority(actor,'review_boot')
            if type(valid_until) is not int or not now < valid_until <= now+30:
                raise Denied('BOOT_REVIEW_EXPIRY_INVALID')
            self.approved=None
            with self.snapshot() as (safety,_):
                safety.db.execute("INSERT INTO incident VALUES(NULL,'BOOT_REVIEWED',?,?,?)",
                                  (self.boot,actor,now))
                record=BootReview(self.boot,self.pid,actor,self.digest(),now,valid_until)
            self.pending=record
            return record

    def approve_boot(self, actor, review):
        with self.lock:
            now=self.now()
            self.authority(actor,'approve_boot')
            if (type(review) is not BootReview or review!=self.pending or self.approved is not None
                or review.boot!=self.boot or review.pid!=self.pid or review.reviewer==actor
                or not review.issued <= now < review.until):
                raise Denied('BOOT_REVIEW_INVALID')
            with self.snapshot() as (safety,_):
                if self.digest()!=review.digest:
                    raise Denied('BOOT_REVIEW_STALE')
                safety.db.execute("INSERT INTO incident VALUES(NULL,'BOOT_APPROVED',?,?,?)",
                                  (self.boot,actor,now))
            self.approved=review
            self.approver=actor
            self.pending=None

    def ready(self):
        now=self.now()
        record=self.approved
        if (record is None or not record.issued <= now < record.until
            or self.roles.get(record.reviewer)!='review_boot'
            or self.roles.get(self.approver)!='approve_boot'):
            raise Denied('BOOT_REVIEW_REQUIRED')
        return now

    def allowed(self, account, workspace, now=None):
        with self.lock:
            try:
                server_now=self.ready()
                # Intake/model-compatible positional time is never authority.
                if now is not None and now!=server_now:
                    raise Denied('SERVER_TIME_REQUIRED')
                return self.guarded.allowed(account,workspace,server_now)
            except Denied:
                return False

    def commit_gate(self, incoming):
        @contextmanager
        def gate():
            with incoming() if incoming else nullcontext() as current:
                checked=self.ready()
                if current is not None and checked!=current:
                    raise Denied('COMMIT_CLOCK_MISMATCH')
                yield checked
        return gate

    def activate(self, account, revision, now, until, key, **kwargs):
        with self.lock:
            if now!=self.ready(): raise Denied('SERVER_TIME_REQUIRED')
            kwargs['commit_guard']=self.commit_gate(kwargs.get('commit_guard'))
            return self.guarded.activate(account,revision,now,until,key,**kwargs)

    def review(self, account, now, checklist, **kwargs):
        with self.lock:
            if now!=self.ready(): raise Denied('SERVER_TIME_REQUIRED')
            kwargs['commit_guard']=self.commit_gate(kwargs.get('commit_guard'))
            return self.guarded.review(account,now,checklist,**kwargs)

    def suspend(self, account, now, actor='TST-support'):
        # Protective restriction is allowed while startup grants are fenced.
        with self.lock:
            if now!=self.now(): raise Denied('SERVER_TIME_REQUIRED')
            return self.guarded.suspend(account,now,actor)

    def revoke(self, account, now, actor='TST-revoker'):
        with self.lock:
            if now!=self.now(): raise Denied('SERVER_TIME_REQUIRED')
            return self.guarded.revoke(account,now,actor)

    def expire(self, account, now, actor='TST-expirer'):
        with self.lock:
            if now!=self.now(): raise Denied('SERVER_TIME_REQUIRED')
            return self.guarded.expire(account,now,actor)
