"""Real lock waits plus final-write rollback through the integrated stack."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from tempfile import TemporaryDirectory
import unittest

from intake import Intake
from model import Model
from rehearsal import Rehearsal, ROLES
from restart import RestartGuard
from safety import GuardedModel, SafetyStore


class CommitTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.f=Rehearsal(tmp.name)
        self.addCleanup(self.f.close)

    def waiting_request(self, action, mutate):
        if action=='activations':
            self.f.approve_start()
            self.assertEqual(self.f.request('reviews')[0],200)
        expected='SAFETY_REVIEW_PENDING' if action=='reviews' else 'APPROVED_FOR_ACTIVATION'
        before=self.f.model.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        ready,start,attempted=Event(),Event(),Event()
        primary_path=self.f.model.db.execute('PRAGMA database_list').fetchone()[2]
        safety_path=str(self.f.safety.path)
        def worker():
            primary=Model(primary_path); safety=SafetyStore(safety_path)
            runtime=RestartGuard(GuardedModel(primary,safety),lambda:self.f.now,ROLES)
            try:
                record=runtime.review_boot('TST-boot-reviewer',valid_until=23)
                runtime.approve_boot('TST-boot-approver',record)
                primary.db.set_trace_callback(lambda sql: attempted.set() if sql=='BEGIN IMMEDIATE' else None)
                ready.set()
                if not start.wait(3): raise AssertionError('request start timeout')
                # Reuse only fixture request serialization and credentials;
                # the actual adapter targets this thread's full guarded stack.
                previous=self.f.intake
                self.f.intake=Intake(runtime,self.f.sessions,lambda:self.f.now)
                try: return self.f.request(action)
                finally: self.f.intake=previous
            finally:
                primary.db.close(); safety.db.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(worker)
            self.assertTrue(ready.wait(3))
            self.f.model.db.execute('BEGIN IMMEDIATE')
            try:
                start.set()
                self.assertTrue(attempted.wait(3))
                self.assertFalse(future.done())
                mutate()
            finally: self.f.model.db.execute('COMMIT')
            self.assertEqual(future.result(timeout=5)[0],403)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],expected)
        self.assertEqual(self.f.model.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],before)
        self.assertEqual(self.f.model.db.execute('SELECT COUNT(*) FROM request').fetchone()[0],0)

    def test_review_revocation_during_primary_lock_wait(self):
        self.waiting_request('reviews',lambda:self.f.sessions.revoke(self.f.credentials['TST-reviewer'][0]))

    def test_activation_revocation_during_primary_lock_wait(self):
        self.waiting_request('activations',lambda:self.f.sessions.revoke(self.f.credentials['TST-activator'][0]))

    def test_session_expiry_during_primary_lock_wait(self):
        self.waiting_request('activations',lambda:setattr(self.f,'now',25))

    def test_boot_lease_expiry_during_primary_lock_wait(self):
        self.waiting_request('activations',lambda:setattr(self.f,'now',23))

    def test_review_expiry_during_primary_lock_wait(self):
        # Reviewer evidence expires before boot/session expiry in this case.
        def expire():
            self.f.model.db.execute('UPDATE review_evidence SET until=4')
            self.f.now=4
        self.waiting_request('activations',expire)

    def test_mandate_expiry_during_primary_lock_wait(self):
        def expire():
            self.f.model.db.execute("UPDATE mandate SET until=4 WHERE role='activate'")
            self.f.now=4
        self.waiting_request('activations',expire)

    def test_revocation_after_last_write_rolls_back_review(self):
        self.f.approve_start()
        original=self.f.model.event
        def revoke_after_write(*args):
            result=original(*args)
            self.f.sessions.revoke(self.f.credentials['TST-reviewer'][0])
            return result
        self.f.model.event=revoke_after_write
        before=self.f.model.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        self.assertEqual(self.f.request('reviews')[0],403)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],'SAFETY_REVIEW_PENDING')
        self.assertEqual(self.f.model.db.execute('SELECT COUNT(*) FROM review_evidence').fetchone()[0],0)
        self.assertEqual(self.f.model.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],before)

    def test_requested_activation_expiry_checked_after_write(self):
        self.f.approve_start()
        self.assertEqual(self.f.request('reviews')[0],200)
        original=self.f.model.event
        def advance(*args):
            result=original(*args)
            self.f.now=4
            return result
        self.f.model.event=advance
        self.assertEqual(self.f.request('activations',until=4)[0],403)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],'APPROVED_FOR_ACTIVATION')
        self.assertEqual(self.f.model.db.execute('SELECT COUNT(*) FROM request').fetchone()[0],0)

    def test_requested_review_expiry_checked_after_write(self):
        self.f.approve_start()
        original=self.f.model.event
        def advance(*args):
            result=original(*args)
            self.f.now=4
            return result
        self.f.model.event=advance
        self.assertEqual(self.f.request('reviews',valid_until=4)[0],403)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],'SAFETY_REVIEW_PENDING')
        self.assertEqual(self.f.model.db.execute('SELECT COUNT(*) FROM review_evidence').fetchone()[0],0)

    def test_activation_time_advance_after_write_rolls_back(self):
        self.f.approve_start()
        self.assertEqual(self.f.request('reviews')[0],200)
        original=self.f.model.event
        def advance_after_write(*args):
            result=original(*args)
            self.f.now=25
            return result
        self.f.model.event=advance_after_write
        self.assertEqual(self.f.request('activations')[0],403)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],'APPROVED_FOR_ACTIVATION')
        self.assertEqual(self.f.model.db.execute('SELECT COUNT(*) FROM request').fetchone()[0],0)

if __name__=='__main__': unittest.main()
