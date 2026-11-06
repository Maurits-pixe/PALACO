"""Negative evidence checks and real two-connection SQLite contention."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Barrier
import unittest

from model import Model, Denied
from test_model import CHECKS


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'synthetic.sqlite')
        self.m = Model(self.path)
        self.addCleanup(self.m.db.close)
        self.m.seed_fixture_mandates()
        self.m.invite('TST-alpha', 'test-token', 0, 10)
        self.m.verify('TST-alpha', 'test-token', 1, 'TST-alpha')
        self.m.stage('TST-alpha', 2)
        self.m.review('TST-alpha', 3, CHECKS)

    def activate(self, model=None, now=4, key='request-1'):
        return (model or self.m).activate('TST-alpha', 1, now, 90, key)

    def assert_blocked(self):
        with self.assertRaises(Denied): self.activate()
        self.assertEqual(self.m.get('TST-alpha')['state'], 'APPROVED_FOR_ACTIVATION')
        self.assertEqual(self.m.db.execute('SELECT COUNT(*) FROM request').fetchone()[0], 0)

    def test_missing_mandate(self):
        self.m.db.execute("DELETE FROM mandate WHERE role='activate'")
        self.assert_blocked()

    def test_revoked_mandate(self):
        self.m.db.execute("UPDATE mandate SET revoked=1 WHERE role='activate'")
        self.assert_blocked()

    def test_expired_mandate(self):
        self.m.db.execute("UPDATE mandate SET until=4 WHERE role='activate'")
        self.assert_blocked()

    def test_wrong_mandate_workspace(self):
        self.m.db.execute("UPDATE mandate SET workspace='other' WHERE role='activate'")
        self.assert_blocked()

    def test_wrong_mandate_scope(self):
        self.m.db.execute("UPDATE mandate SET scope='synthetic:write' WHERE role='activate'")
        self.assert_blocked()

    def test_reviewer_mandate_revoked_after_approval(self):
        self.m.db.execute("UPDATE mandate SET revoked=1 WHERE role='review'")
        self.assert_blocked()

    def test_missing_evidence(self):
        self.m.db.execute('DELETE FROM review_evidence')
        self.assert_blocked()

    def test_expired_evidence(self):
        self.m.db.execute('UPDATE review_evidence SET until=4')
        self.assert_blocked()

    def test_policy_changed_after_review(self):
        self.m.db.execute("UPDATE policy SET version='staging-v2'")
        self.assert_blocked()

    def test_tampered_evidence_binding(self):
        for field, value in [('revision',2),('workspace','other'),('scope','other'),('reviewer','other')]:
            with self.subTest(field=field):
                self.m.db.execute('SAVEPOINT mutation')
                self.m.db.execute(f'UPDATE review_evidence SET {field}=?', (value,))
                # Commit the fixture mutation before invoking the transactional gate.
                self.m.db.execute('RELEASE mutation')
                self.assert_blocked()
                row = self.m.get('TST-alpha')
                self.m.db.execute('UPDATE review_evidence SET revision=1,workspace=?,scope=?,reviewer=?',
                                 (row['workspace'],row['scope'],row['reviewer']))

    def test_persistence_reopen(self):
        self.activate()
        other = Model(self.path)
        try:
            self.assertTrue(other.allowed('TST-alpha','synthetic',5))
            self.assertEqual(other.db.execute('SELECT COUNT(*) FROM request').fetchone()[0],1)
        finally: other.db.close()

    def test_two_connections_duplicate_activation(self):
        barrier = Barrier(2)
        def worker():
            model = Model(self.path)
            try:
                barrier.wait(timeout=3)
                return self.activate(model)
            finally: model.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            self.assertEqual([f.result(timeout=5) for f in futures], ['ACTIVE','ACTIVE'])
        self.assertEqual(self.m.db.execute("SELECT COUNT(*) FROM audit WHERE current='ACTIVE'").fetchone()[0],1)

    def test_inflight_activation_waits_for_mandate_revocation(self):
        self.contended_revocation("UPDATE mandate SET revoked=1 WHERE role='activate'")

    def test_inflight_activation_waits_for_suspension(self):
        self.contended_revocation("UPDATE account SET state='SUSPENDED' WHERE id='TST-alpha'")

    def contended_revocation(self, mutation):
        ready, start, attempted = Event(), Event(), Event()
        def worker():
            model = Model(self.path)
            model.db.set_trace_callback(lambda sql: attempted.set() if sql == 'BEGIN IMMEDIATE' else None)
            ready.set()
            try:
                if not start.wait(3): raise AssertionError('start timeout')
                try: self.activate(model)
                except Denied: return 'DENIED'
                return 'UNEXPECTED_ACTIVATION'
            finally: model.db.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            self.assertTrue(ready.wait(3))
            with self.m.transaction():
                if mutation.startswith('UPDATE account'):
                    self.m.transition('TST-alpha', 'TST-support',
                                      'APPROVED_FOR_ACTIVATION', 'SUSPENDED', 4)
                else:
                    self.m.db.execute(mutation)
                start.set()
                self.assertTrue(attempted.wait(3))
                self.assertFalse(future.done())
            self.assertEqual(future.result(timeout=5), 'DENIED')
        self.assertEqual(self.m.db.execute('SELECT COUNT(*) FROM request').fetchone()[0],0)
        self.assertFalse(self.m.allowed('TST-alpha','synthetic',5))

if __name__ == '__main__': unittest.main()
