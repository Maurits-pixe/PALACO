from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from model import Model, Denied
from rehearsal import Rehearsal
from restart import RestartGuard
from safety import GuardedModel, SafetyStore


class TerminalTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.f=Rehearsal(tmp.name); self.addCleanup(self.f.close)

    def activate(self):
        self.f.approve_start()
        self.assertEqual(self.f.request('reviews')[0],200)
        self.assertEqual(self.f.request('activations')[0],200)

    def fail_audit(self):
        self.f.model.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'injected'); END")

    def assert_closed(self,state):
        self.assertEqual(self.f.model.get('TST-alpha')['state'],state)
        self.assertFalse(self.f.active())
        self.assertEqual(self.f.request('activations',until=self.f.now+1)[0],403)

    def test_active_revocation_is_permanent(self):
        self.activate(); self.f.now=4
        self.assertEqual(self.f.runtime.revoke('TST-alpha',4),'AUDIT_DELIVERED')
        self.assert_closed('REVOKED')
        event=self.f.model.db.execute("SELECT * FROM audit WHERE event='account.revoked'").fetchone()
        self.assertEqual((event['actor'],event['at'],event['previous']),('TST-revoker',4,'ACTIVE'))

    def test_staged_revocation_does_not_require_serving_lease(self):
        self.assertEqual(self.f.runtime.revoke('TST-alpha',3),'AUDIT_DELIVERED')
        self.assert_closed('REVOKED')

    def test_suspended_account_can_be_definitively_revoked(self):
        self.activate(); self.f.runtime.suspend('TST-alpha',3)
        self.assertEqual(self.f.runtime.revoke('TST-alpha',3),'AUDIT_DELIVERED')
        self.assert_closed('REVOKED')
        row=self.f.model.db.execute('SELECT previous FROM terminal_outbox').fetchone()
        self.assertEqual(row[0],'SUSPENDED')

    def test_expired_account_gets_explicit_terminal_event(self):
        self.activate(); self.f.now=24
        self.assertFalse(self.f.active())  # Timestamp denial precedes event processing.
        self.assertEqual(self.f.runtime.expire('TST-alpha',24),'AUDIT_DELIVERED')
        self.assert_closed('EXPIRED')
        self.assertEqual(self.f.model.db.execute("SELECT at FROM audit WHERE event='account.expired'").fetchone()[0],24)

    def test_invitation_expiry_consumes_no_invitation(self):
        self.f.model.invite('TST-beta','fixture-token',0,10)
        self.f.now=10
        self.assertEqual(self.f.runtime.expire('TST-beta',10),'AUDIT_DELIVERED')
        self.assertEqual(self.f.model.get('TST-beta')['used'],0)
        with self.assertRaises(Denied): self.f.model.verify('TST-beta','fixture-token',10,'TST-beta')
        self.assertEqual(self.f.model.get('TST-beta')['state'],'EXPIRED')

    def test_early_expiry_does_not_create_independent_block(self):
        self.activate()
        with self.assertRaisesRegex(Denied,'EXPIRY_NOT_DUE'): self.f.runtime.expire('TST-alpha',3)
        self.assertTrue(self.f.active())
        self.assertEqual(self.f.safety.db.execute('SELECT COUNT(*) FROM denied_account').fetchone()[0],0)

    def test_staged_expiry_without_deadline_is_refused(self):
        with self.assertRaisesRegex(Denied,'EXPIRY_NOT_DUE'): self.f.runtime.expire('TST-alpha',3)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],'SAFETY_REVIEW_PENDING')

    def test_terminal_states_cannot_change_to_each_other(self):
        self.activate(); self.f.now=4; self.f.runtime.revoke('TST-alpha',4)
        with self.assertRaises(Denied): self.f.runtime.expire('TST-alpha',4)
        self.assert_closed('REVOKED')

    def test_wrong_role_and_revoked_mandate_do_not_block_account(self):
        self.activate()
        with self.assertRaises(Denied): self.f.runtime.revoke('TST-alpha',3,'TST-support')
        self.f.model.db.execute("UPDATE mandate SET revoked=1 WHERE role='revoke'")
        with self.assertRaises(Denied): self.f.runtime.revoke('TST-alpha',3)
        self.assertTrue(self.f.active())
        self.assertEqual(self.f.safety.db.execute('SELECT COUNT(*) FROM denied_account').fetchone()[0],0)

    def test_audit_outage_preserves_terminal_state_and_evidence(self):
        self.activate(); self.fail_audit(); self.f.now=4
        self.assertEqual(self.f.runtime.revoke('TST-alpha',4),'AUDIT_PENDING')
        self.assert_closed('REVOKED')
        item=self.f.model.pending_terminal_events()[0]
        self.assertEqual((item['actor'],item['occurred']),('TST-revoker',4))
        self.f.restart()
        with self.assertRaisesRegex(Denied,'AUDIT_RECONCILIATION_REQUIRED'): self.f.approve_start()

    def test_reconciliation_preserves_terminal_block_after_new_boot_review(self):
        self.activate(); self.fail_audit(); self.f.now=4
        self.f.runtime.revoke('TST-alpha',4)
        item=self.f.model.pending_terminal_events()[0]
        self.f.model.db.execute('DROP TRIGGER fail_audit')
        for _ in range(2): self.assertEqual(self.f.model.deliver_terminal(item['id']),'AUDIT_DELIVERED')
        self.assertEqual(self.f.model.db.execute("SELECT COUNT(*) FROM audit WHERE event='account.revoked'").fetchone()[0],1)
        self.f.restart(); self.f.approve_start()
        self.assert_closed('REVOKED')

    def test_expiry_audit_outage_preserves_expired_state(self):
        self.activate(); self.fail_audit(); self.f.now=24
        self.assertEqual(self.f.runtime.expire('TST-alpha',24),'AUDIT_PENDING')
        self.assert_closed('EXPIRED')

    def test_repeated_revocation_keeps_original_actor_and_time(self):
        self.activate(); self.f.now=4
        self.f.runtime.revoke('TST-alpha',4); self.f.now=5
        self.assertEqual(self.f.runtime.revoke('TST-alpha',5),'AUDIT_DELIVERED')
        row=self.f.model.db.execute('SELECT * FROM terminal_outbox').fetchall()
        self.assertEqual(len(row),1); self.assertEqual(row[0]['occurred'],4)

    def test_outbox_write_failure_still_has_independent_deny(self):
        self.activate()
        self.f.model.db.execute("CREATE TRIGGER fail_terminal BEFORE INSERT ON terminal_outbox BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(Denied): self.f.runtime.revoke('TST-alpha',3)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],'ACTIVE')
        self.assertFalse(self.f.active())
        self.assertEqual(self.f.safety.db.execute('SELECT state FROM circuit').fetchone()[0],'LOCKED')

    def test_terminal_evidence_is_immutable(self):
        self.f.runtime.revoke('TST-alpha',3)
        for sql in ('DELETE FROM terminal_outbox',"UPDATE terminal_outbox SET actor='other'",
                    'UPDATE terminal_outbox SET occurred=99','UPDATE terminal_outbox SET audit_sequence=NULL'):
            with self.assertRaises(sqlite3.IntegrityError): self.f.model.db.execute(sql)

    def test_recovery_and_new_invitation_cannot_reactivate_same_account(self):
        self.f.runtime.revoke('TST-alpha',3)
        self.assertEqual(self.f.model.recover_authentication('TST-alpha'),'REVOKED')
        with self.assertRaises(sqlite3.IntegrityError): self.f.model.invite('TST-alpha','new-token',4,10)
        self.assert_closed('REVOKED')

    def test_terminal_commit_survives_process_exit_before_delivery(self):
        self.activate()
        path=self.f.model.db.execute('PRAGMA database_list').fetchone()[2]
        code="""from model import Model
import os,sys
m=Model(sys.argv[1]);m.deliver_terminal=lambda _:os._exit(26)
m.revoke('TST-alpha',4)
"""
        result=subprocess.run([sys.executable,'-c',code,path],cwd=Path(__file__).parent,
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,26,result.stderr)
        self.assert_closed('REVOKED')
        self.assertEqual(len(self.f.model.pending_terminal_events()),1)

    def test_concurrent_activation_and_revocation_end_closed(self):
        self.f.approve_start(); self.assertEqual(self.f.request('reviews')[0],200)
        primary=self.f.model.db.execute('PRAGMA database_list').fetchone()[2]
        safety=str(self.f.safety.path); barrier=Barrier(2)
        def worker(revoke):
            m=Model(primary); s=SafetyStore(safety); g=GuardedModel(m,s)
            try:
                barrier.wait(timeout=3)
                try: return g.revoke('TST-alpha',3) if revoke else g.activate('TST-alpha',1,3,24,'race-request')
                except Denied: return 'DENIED'
            finally: m.db.close(); s.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(worker,True); second=pool.submit(worker,False)
            self.assertEqual(first.result(timeout=5),'AUDIT_DELIVERED')
            self.assertIn(second.result(timeout=5),['ACTIVE','DENIED'])
        self.assert_closed('REVOKED')

if __name__=='__main__': unittest.main()
