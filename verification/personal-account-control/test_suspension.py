"""Audit outage, recovery durability and concurrent suspension tests."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from model import Model, Denied
from test_model import CHECKS


class SuspensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'synthetic.sqlite')
        self.m=Model(self.path)
        self.addCleanup(self.m.db.close)
        self.m.seed_fixture_mandates()
        self.m.invite('TST-alpha','fixture-token',0,10)
        self.m.verify('TST-alpha','fixture-token',1,'TST-alpha')
        self.m.stage('TST-alpha',2)
        self.m.review('TST-alpha',3,CHECKS)
        self.m.activate('TST-alpha',1,4,90,'request-1')

    def fail_audit(self, mode='ABORT'):
        # ABORT and ROLLBACK have different transaction behavior: test both.
        self.m.db.execute(f"CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN SELECT RAISE({mode},'injected'); END")

    def assert_blocked(self):
        self.assertEqual(self.m.get('TST-alpha')['state'],'SUSPENDED')
        self.assertFalse(self.m.allowed('TST-alpha','synthetic',6))
        with self.assertRaises(Denied):
            self.m.activate('TST-alpha',1,6,90,'request-1')

    def test_audit_abort_preserves_block_and_pending_evidence(self):
        self.fail_audit()
        self.assertEqual(self.m.suspend('TST-alpha',5),'AUDIT_PENDING')
        self.assert_blocked()
        pending=self.m.pending_suspensions()
        self.assertEqual(len(pending),1)
        self.assertEqual((pending[0]['actor'],pending[0]['occurred'],pending[0]['previous']),
                         ('TST-support',5,'ACTIVE'))

    def test_audit_rollback_preserves_prior_commit(self):
        self.fail_audit('ROLLBACK')
        self.assertEqual(self.m.suspend('TST-alpha',5),'AUDIT_PENDING')
        self.assert_blocked()
        self.assertEqual(len(self.m.pending_suspensions()),1)

    def test_recovery_retains_original_time_and_never_reactivates(self):
        self.fail_audit()
        self.m.suspend('TST-alpha',5)
        item=self.m.pending_suspensions()[0]['id']
        self.m.db.execute('DROP TRIGGER fail_audit')
        for _ in range(2):
            self.assertEqual(self.m.deliver_suspension(item),'AUDIT_DELIVERED')
        self.assertEqual(len(self.m.pending_suspensions()),0)
        events=self.m.db.execute("SELECT * FROM audit WHERE event='account.suspended'").fetchall()
        self.assertEqual(len(events),1)
        self.assertEqual((events[0]['actor'],events[0]['at']),('TST-support',5))
        self.assert_blocked()

    def test_repeated_suspension_does_not_duplicate_outbox(self):
        self.fail_audit()
        self.assertEqual(self.m.suspend('TST-alpha',5),'AUDIT_PENDING')
        self.assertEqual(self.m.suspend('TST-alpha',6),'AUDIT_PENDING')
        self.assertEqual(self.m.db.execute('SELECT COUNT(*) FROM suspension_outbox').fetchone()[0],1)
        self.assertEqual(self.m.pending_suspensions()[0]['occurred'],5)

    def test_normal_suspension_delivers_audit(self):
        self.assertEqual(self.m.suspend('TST-alpha',5),'AUDIT_DELIVERED')
        self.assert_blocked()
        self.assertEqual(len(self.m.pending_suspensions()),0)

    def test_outbox_failure_does_not_report_success(self):
        self.m.db.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON suspension_outbox BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.Error): self.m.suspend('TST-alpha',5)
        self.assertEqual(self.m.get('TST-alpha')['state'],'ACTIVE')
        self.assertEqual(len(self.m.pending_suspensions()),0)
        # This distinct shared-storage outage remains an explicit runtime blocker.

    def test_unauthorized_actor_cannot_suspend(self):
        with self.assertRaises(Denied): self.m.suspend('TST-alpha',5,actor='TST-reviewer')
        self.assertEqual(self.m.get('TST-alpha')['state'],'ACTIVE')
        self.assertEqual(len(self.m.pending_suspensions()),0)

    def test_immutable_outbox_payload_and_receipt(self):
        self.m.suspend('TST-alpha',5)
        for sql in ["UPDATE suspension_outbox SET actor='other'",
                    'UPDATE suspension_outbox SET occurred=9',
                    'UPDATE suspension_outbox SET audit_sequence=NULL',
                    'DELETE FROM suspension_outbox']:
            with self.assertRaises(sqlite3.IntegrityError): self.m.db.execute(sql)

    def test_separate_process_observes_block_and_recovers(self):
        self.fail_audit()
        self.m.suspend('TST-alpha',5)
        code='''from model import Model
import sys
m=Model(sys.argv[1])
assert not m.allowed('TST-alpha','synthetic',6)
p=m.pending_suspensions()
assert len(p)==1 and p[0]['occurred']==5
assert m.deliver_suspension(p[0]['id'])=='AUDIT_PENDING'
m.db.execute('DROP TRIGGER fail_audit')
assert m.deliver_suspension(p[0]['id'])=='AUDIT_DELIVERED'
assert not m.allowed('TST-alpha','synthetic',6)
assert not m.pending_suspensions()
m.db.close()
'''
        result=subprocess.run([sys.executable,'-c',code,self.path],
            cwd=Path(__file__).parent,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assert_blocked()

    def test_process_exit_between_block_commit_and_audit(self):
        code = """from model import Model
import os, sys
m=Model(sys.argv[1])
m.deliver_suspension=lambda _: os._exit(23)
m.suspend('TST-alpha',5)
"""
        result=subprocess.run([sys.executable,'-c',code,self.path],
            cwd=Path(__file__).parent,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,23)
        self.assert_blocked()
        pending=self.m.pending_suspensions()
        self.assertEqual(len(pending),1)
        self.assertEqual(self.m.deliver_suspension(pending[0]['id']),'AUDIT_DELIVERED')
        self.assert_blocked()

    def test_concurrent_recovery_delivers_once(self):
        self.fail_audit(); self.m.suspend('TST-alpha',5)
        item=self.m.pending_suspensions()[0]['id']
        self.m.db.execute('DROP TRIGGER fail_audit')
        barrier=Barrier(2)
        def worker():
            m=Model(self.path)
            try:
                barrier.wait(timeout=3)
                return m.deliver_suspension(item)
            finally: m.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker) for _ in range(2)]
            self.assertEqual([f.result(timeout=5) for f in futures],['AUDIT_DELIVERED']*2)
        self.assertEqual(self.m.db.execute("SELECT COUNT(*) FROM audit WHERE event='account.suspended'").fetchone()[0],1)
        self.assert_blocked()

    def test_activation_replay_races_with_suspension_during_outage(self):
        self.fail_audit()
        barrier=Barrier(2)
        def worker(suspend):
            m=Model(self.path)
            try:
                barrier.wait(timeout=3)
                if suspend: return m.suspend('TST-alpha',5)
                try: return m.activate('TST-alpha',1,5,90,'request-1')
                except Denied: return 'DENIED'
            finally: m.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(worker,True); second=pool.submit(worker,False)
            self.assertEqual(first.result(timeout=5),'AUDIT_PENDING')
            self.assertIn(second.result(timeout=5),['ACTIVE','DENIED'])
        self.assert_blocked()
        self.assertEqual(len(self.m.pending_suspensions()),1)

if __name__=='__main__': unittest.main()
