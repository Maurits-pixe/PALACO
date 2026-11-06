from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from model import Model, Denied
from safety import SafetyStore, GuardedModel
from test_model import CHECKS


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.primary=str(Path(self.tmp.name)/'accounts.sqlite')
        self.safety_path=str(Path(self.tmp.name)/'safety.sqlite')
        self.m=Model(self.primary)
        self.addCleanup(self.m.db.close)
        self.m.seed_fixture_mandates()
        self.m.invite('TST-alpha','fixture-token',0,10)
        self.m.verify('TST-alpha','fixture-token',1,'TST-alpha')
        self.m.stage('TST-alpha',2)
        self.m.review('TST-alpha',3,CHECKS)
        self.m.activate('TST-alpha',1,4,90,'request-1')
        self.s=SafetyStore(self.safety_path)
        self.addCleanup(self.s.db.close)
        self.g=GuardedModel(self.m,self.s)

    def provision(self): self.s.fixture_provision_once()

    def fail_outbox(self):
        self.m.db.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON suspension_outbox BEGIN SELECT RAISE(ABORT,'injected'); END")

    def test_starts_denied_until_explicit_fixture_setup(self):
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',5))
        self.provision()
        self.assertTrue(self.g.allowed('TST-alpha','synthetic',5))

    def test_normal_suspension_has_independent_intent(self):
        self.provision()
        self.assertEqual(self.g.suspend('TST-alpha',5),'AUDIT_DELIVERED')
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',6))
        row=self.s.db.execute('SELECT * FROM denied_account').fetchone()
        self.assertEqual((row['account'],row['actor'],row['occurred']),('TST-alpha','TST-support',5))

    def test_outbox_write_failure_blocks_despite_primary_active(self):
        self.provision(); self.fail_outbox()
        with self.assertRaisesRegex(Denied,'PRIMARY_STORAGE_FAILURE_SAFETY_LOCKED'):
            self.g.suspend('TST-alpha',5)
        self.assertEqual(self.m.get('TST-alpha')['state'],'ACTIVE')
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',6))
        self.assertEqual(self.s.db.execute('SELECT state FROM circuit').fetchone()[0],'LOCKED')

    def test_no_auto_unlock_when_primary_recovers(self):
        self.provision(); self.fail_outbox()
        with self.assertRaises(Denied): self.g.suspend('TST-alpha',5)
        self.m.db.execute('DROP TRIGGER fail_outbox')
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',6))
        with self.assertRaises(Denied): self.s.fixture_provision_once()
        with self.assertRaises(Denied): self.g.activate('TST-alpha',1,6,90,'request-1')

    def test_primary_read_failure_trips_circuit(self):
        self.provision(); self.m.db.close()
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',5))
        self.assertEqual(self.s.db.execute('SELECT state FROM circuit').fetchone()[0],'LOCKED')
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM incident WHERE reason='PRIMARY_STORAGE_FAILURE'").fetchone()[0],1)

    def test_safety_connection_unavailable_denies(self):
        self.provision(); self.s.db.close()
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',5))
        with self.assertRaises(Denied): self.g.activate('TST-alpha',1,5,90,'request-1')

    def test_safety_read_only_denies_without_trusting_cached_state(self):
        self.provision(); self.s.db.execute('PRAGMA query_only=ON')
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',5))
        self.s.db.execute('PRAGMA query_only=OFF')
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',6))

    def test_safety_store_write_failure_prevents_primary_suspension(self):
        self.provision()
        self.s.db.execute("CREATE TRIGGER fail_intent BEFORE INSERT ON denied_account BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaisesRegex(Denied,'SAFETY_UNAVAILABLE'): self.g.suspend('TST-alpha',5)
        self.assertEqual(self.m.get('TST-alpha')['state'],'ACTIVE')
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',6))

    def test_unauthorized_actor_does_not_create_intent(self):
        self.provision()
        with self.assertRaises(Denied): self.g.suspend('TST-alpha',5,'TST-reviewer')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM denied_account').fetchone()[0],0)
        self.assertTrue(self.g.allowed('TST-alpha','synthetic',6))

    def test_revoked_mandate_does_not_create_intent(self):
        self.provision()
        self.m.db.execute("UPDATE mandate SET revoked=1 WHERE role='suspend'")
        with self.assertRaises(Denied): self.g.suspend('TST-alpha',5)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM denied_account').fetchone()[0],0)

    def test_reopen_preserves_global_lock(self):
        self.provision(); self.fail_outbox()
        with self.assertRaises(Denied): self.g.suspend('TST-alpha',5)
        other=SafetyStore(self.safety_path)
        try:
            self.assertFalse(GuardedModel(self.m,other).allowed('TST-alpha','synthetic',6))
            with self.assertRaises(Denied): other.fixture_provision_once()
        finally: other.db.close()

    def test_missing_store_replacement_defaults_to_denied(self):
        self.provision()
        other=SafetyStore(str(Path(self.tmp.name)/'replacement.sqlite'))
        try: self.assertFalse(GuardedModel(self.m,other).allowed('TST-alpha','synthetic',5))
        finally: other.db.close()

    def test_same_database_refused(self):
        other=SafetyStore(self.primary)
        try:
            with self.assertRaises(ValueError): GuardedModel(self.m,other)
        finally: other.db.close()

    def test_process_exit_after_intent_preserves_independent_block(self):
        self.provision()
        code='''from model import Model
from safety import SafetyStore, GuardedModel
import os,sys
m=Model(sys.argv[1]); s=SafetyStore(sys.argv[2]); g=GuardedModel(m,s)
m.suspend=lambda *a,**kw: os._exit(24)
g.suspend('TST-alpha',5)
'''
        result=subprocess.run([sys.executable,'-c',code,self.primary,self.safety_path],
            cwd=Path(__file__).parent,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,24,result.stderr)
        self.assertEqual(self.m.get('TST-alpha')['state'],'ACTIVE')
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',6))
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM denied_account').fetchone()[0],1)

    def test_concurrent_guarded_replay_and_failed_suspension(self):
        self.provision(); self.fail_outbox()
        barrier=Barrier(2)
        def worker(suspend):
            model=Model(self.primary); safety=SafetyStore(self.safety_path)
            guard=GuardedModel(model,safety)
            try:
                barrier.wait(timeout=3)
                try:
                    return guard.suspend('TST-alpha',5) if suspend else guard.activate('TST-alpha',1,5,90,'request-1')
                except Denied: return 'DENIED'
            finally:
                model.db.close(); safety.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(worker,True); second=pool.submit(worker,False)
            self.assertEqual(first.result(timeout=5),'DENIED')
            self.assertIn(second.result(timeout=5),['ACTIVE','DENIED'])
        self.assertFalse(self.g.allowed('TST-alpha','synthetic',6))

    def test_incident_evidence_immutable(self):
        self.provision()
        for sql in ['DELETE FROM incident',"UPDATE incident SET reason='other'"]:
            with self.assertRaises(sqlite3.IntegrityError): self.s.db.execute(sql)

if __name__=='__main__': unittest.main()
