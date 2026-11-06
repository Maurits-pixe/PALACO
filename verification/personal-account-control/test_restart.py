from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from model import Model, Denied
from safety import SafetyStore, GuardedModel
from restart import RestartGuard
from test_model import CHECKS

ROLES={'TST-boot-reviewer':'review_boot','TST-boot-approver':'approve_boot'}


class RestartTests(unittest.TestCase):
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
        self.s.fixture_provision_once()
        self.g=GuardedModel(self.m,self.s)
        self.time=5
        self.r=RestartGuard(self.g,lambda:self.time,ROLES)

    def approve(self):
        review=self.r.review_boot('TST-boot-reviewer',valid_until=20)
        self.r.approve_boot('TST-boot-approver',review)
        return review

    def test_open_storage_alone_never_grants_startup(self):
        self.assertTrue(self.g.allowed('TST-alpha','synthetic',5))
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))
        with self.assertRaises(Denied): self.r.activate('TST-alpha',1,5,90,'request-1')

    def test_separate_roles_release_only_this_boot(self):
        self.approve()
        self.assertTrue(self.r.allowed('TST-alpha','synthetic'))
        other=RestartGuard(self.g,lambda:self.time,ROLES)
        self.assertFalse(other.allowed('TST-alpha','synthetic'))
        self.assertNotEqual(other.boot,self.r.boot)

    def test_wrong_roles_cannot_review_or_approve(self):
        with self.assertRaises(Denied): self.r.review_boot('unknown',valid_until=20)
        record=self.r.review_boot('TST-boot-reviewer',valid_until=20)
        with self.assertRaises(Denied): self.r.approve_boot('TST-boot-reviewer',record)
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))

    def test_record_from_other_boot_refused(self):
        record=self.r.review_boot('TST-boot-reviewer',valid_until=20)
        other=RestartGuard(self.g,lambda:self.time,ROLES)
        with self.assertRaises(Denied): other.approve_boot('TST-boot-approver',record)

    def test_tampered_record_refused(self):
        record=self.r.review_boot('TST-boot-reviewer',valid_until=20)
        for modified in [replace(record,digest='0'*64),replace(record,until=100),replace(record,pid=-1)]:
            with self.assertRaises(Denied): self.r.approve_boot('TST-boot-approver',modified)

    def test_expired_review_and_lease(self):
        self.approve()
        self.time=20
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))
        with self.assertRaises(Denied): self.r.activate('TST-alpha',1,20,90,'request-1')

    def test_approval_after_expiry_refused(self):
        record=self.r.review_boot('TST-boot-reviewer',valid_until=20)
        self.time=20
        with self.assertRaises(Denied): self.r.approve_boot('TST-boot-approver',record)

    def test_invalid_lifetime(self):
        for until in [5,36,True]:
            with self.assertRaises(Denied): self.r.review_boot('TST-boot-reviewer',valid_until=until)

    def test_policy_change_invalidates_pending_review(self):
        record=self.r.review_boot('TST-boot-reviewer',valid_until=20)
        self.m.db.execute("UPDATE policy SET version='staging-v2'")
        with self.assertRaisesRegex(Denied,'STALE'): self.r.approve_boot('TST-boot-approver',record)

    def test_safety_incident_invalidates_pending_review(self):
        record=self.r.review_boot('TST-boot-reviewer',valid_until=20)
        self.s.db.execute("INSERT INTO incident VALUES(NULL,'FIXTURE_CHANGE',NULL,NULL,5)")
        with self.assertRaisesRegex(Denied,'STALE'): self.r.approve_boot('TST-boot-approver',record)

    def test_locked_circuit_cannot_be_reset_by_boot_approval(self):
        self.s.db.execute("UPDATE circuit SET state='LOCKED'")
        with self.assertRaises(Denied): self.approve()
        self.assertEqual(self.s.db.execute('SELECT state FROM circuit').fetchone()[0],'LOCKED')

    def test_pending_audit_requires_reconciliation(self):
        self.m.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'injected'); END")
        self.m.suspend('TST-alpha',5)
        with self.assertRaisesRegex(Denied,'AUDIT_RECONCILIATION_REQUIRED'): self.approve()
        self.m.db.execute('DROP TRIGGER fail_audit')
        self.m.deliver_suspension(self.m.pending_suspensions()[0]['id'])
        self.approve()
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))

    def test_independent_intent_requires_primary_reconciliation(self):
        self.s.db.execute("INSERT INTO denied_account VALUES('TST-alpha','TST-support',5)")
        with self.assertRaisesRegex(Denied,'ACCOUNT_RECONCILIATION_REQUIRED'): self.approve()
        self.m.suspend('TST-alpha',5)
        self.approve()
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM denied_account').fetchone()[0],1)

    def test_clock_rollback_latches_fence(self):
        self.approve(); self.time=4
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))
        self.time=6
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))

    def test_pid_change_fences_inherited_approval(self):
        self.approve()
        with patch('restart.os.getpid',return_value=self.r.pid+1):
            self.assertFalse(self.r.allowed('TST-alpha','synthetic'))
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))

    def test_failed_approval_audit_never_releases(self):
        record=self.r.review_boot('TST-boot-reviewer',valid_until=20)
        self.s.db.execute("CREATE TRIGGER fail_incident BEFORE INSERT ON incident BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(Denied): self.r.approve_boot('TST-boot-approver',record)
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))

    def test_suspension_allowed_while_startup_fenced(self):
        self.assertEqual(self.r.suspend('TST-alpha',5),'AUDIT_DELIVERED')
        self.assertEqual(self.m.get('TST-alpha')['state'],'SUSPENDED')
        self.assertFalse(self.r.allowed('TST-alpha','synthetic'))

    def test_restored_stale_open_stores_do_not_restore_boot_authority(self):
        primary_copy=self.primary+'.snapshot'
        safety_copy=self.safety_path+'.snapshot'
        shutil.copyfile(self.primary,primary_copy)
        shutil.copyfile(self.safety_path,safety_copy)
        self.approve()
        self.g.suspend('TST-alpha',5)
        self.m.db.close(); self.s.db.close()
        shutil.copyfile(primary_copy,self.primary)
        shutil.copyfile(safety_copy,self.safety_path)
        primary=Model(self.primary); safety=SafetyStore(self.safety_path)
        try:
            guard=GuardedModel(primary,safety)
            # Both restored stores have lost the later suspension: startup
            # still must not silently restore serving authority.
            self.assertTrue(guard.allowed('TST-alpha','synthetic',6))
            fresh=RestartGuard(guard,lambda:6,ROLES)
            self.assertFalse(fresh.allowed('TST-alpha','synthetic'))
        finally:
            primary.db.close(); safety.db.close()

    def test_separate_process_starts_fenced_with_open_stores(self):
        self.approve()
        code='''from model import Model
from safety import SafetyStore,GuardedModel
from restart import RestartGuard
import sys
m=Model(sys.argv[1]);s=SafetyStore(sys.argv[2]);g=GuardedModel(m,s)
assert g.allowed('TST-alpha','synthetic',6)
r=RestartGuard(g,lambda:6,{})
assert not r.allowed('TST-alpha','synthetic')
try:
 r.activate('TST-alpha',1,6,90,'request-1')
except ValueError:
 pass
else:
 raise AssertionError('startup bypass')
m.db.close();s.db.close()
'''
        result=subprocess.run([sys.executable,'-c',code,self.primary,self.safety_path],
            cwd=Path(__file__).parent,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__': unittest.main()
