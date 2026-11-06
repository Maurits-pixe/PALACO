import sqlite3
import unittest
from model import Model, Denied

CHECKS = dict.fromkeys(('purpose','scope','privacy','risk','escalation','recovery',
                       'clinical_boundary','human_owner','consent_basis'), True)

class Acceptance(unittest.TestCase):
    def setUp(self):
        self.m = Model()
        self.addCleanup(self.m.db.close)
        self.m.seed_fixture_mandates()
        self.m.invite('TST-alpha', 'synthetic-test-token', 0, 10)

    def ready(self):
        self.m.verify('TST-alpha', 'synthetic-test-token', 1, 'TST-alpha')
        self.m.stage('TST-alpha', 2)
        self.m.review('TST-alpha', 3, CHECKS)

    def activate(self, **kw):
        return self.m.activate('TST-alpha', 1, 4, 20, 'request-1', **kw)

    def test_S01_valid_chain(self):
        self.ready(); self.activate()
        self.assertTrue(self.m.allowed('TST-alpha', 'synthetic', 5))
        states = [r[0] for r in self.m.db.execute('SELECT current FROM audit ORDER BY sequence')]
        self.assertEqual(states, ['INVITED','INVITATION_VERIFIED','ACCOUNT_STAGED',
            'SAFETY_REVIEW_PENDING','APPROVED_FOR_ACTIVATION','ACTIVE'])

    def test_S02_invalid_invitation(self):
        for token, now, recipient in [('wrong',1,'TST-alpha'),('synthetic-test-token',10,'TST-alpha'),
                                      ('synthetic-test-token',1,'TST-beta')]:
            with self.assertRaises(Denied): self.m.verify('TST-alpha',token,now,recipient)
        self.ready()
        with self.assertRaises(Denied): self.m.verify('TST-alpha','synthetic-test-token',4,'TST-alpha')

    def test_S03_actor_and_separation(self):
        self.ready()
        with self.assertRaises(Denied): self.activate(actor='unknown')
        self.m.roles['TST-reviewer'] = 'activate'
        with self.assertRaises(Denied): self.activate(actor='TST-reviewer')

    def test_S04_unknown_check(self):
        self.m.verify('TST-alpha','synthetic-test-token',1,'TST-alpha'); self.m.stage('TST-alpha',2)
        with self.assertRaises(Denied): self.m.review('TST-alpha',3,{**CHECKS,'risk':None})
        self.assertEqual(self.m.get('TST-alpha')['state'],'SAFETY_REVIEW_PENDING')

    def test_S05_scope_invalidates(self):
        self.ready(); self.m.change_scope('TST-alpha','synthetic:write',4)
        with self.assertRaises(Denied): self.activate()
        self.assertIsNone(self.m.get('TST-alpha')['reviewed'])

    def test_S06_idempotency(self):
        self.ready(); self.activate(); self.activate()
        self.assertEqual(self.m.db.execute('SELECT COUNT(*) FROM request').fetchone()[0],1)
        with self.assertRaises(Denied): self.m.activate('TST-alpha',1,4,21,'request-1')
        with self.assertRaises(Denied): self.m.activate('TST-alpha',1,20,20,'request-1')

    def test_S07_completed_suspension_blocks_commit(self):
        self.ready(); self.m.suspend('TST-alpha',4)
        with self.assertRaises(Denied): self.activate()
        self.assertFalse(self.m.allowed('TST-alpha','synthetic',5))

    def test_S08_audit_failure_rolls_back(self):
        self.ready()
        self.m.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.activate()
        self.assertEqual(self.m.get('TST-alpha')['state'],'APPROVED_FOR_ACTIVATION')
        self.assertEqual(self.m.db.execute('SELECT COUNT(*) FROM request').fetchone()[0],0)

    def test_S09_suspension_rechecks_access(self):
        self.ready(); self.activate(); self.m.suspend('TST-alpha',5)
        self.assertFalse(self.m.allowed('TST-alpha','synthetic',6))
        with self.assertRaises(Denied): self.activate()

    def test_S10_recovery_no_grant(self):
        self.ready(); self.activate(); self.m.suspend('TST-alpha',5)
        self.assertEqual(self.m.recover_authentication('TST-alpha'),'SUSPENDED')
        self.assertFalse(self.m.allowed('TST-alpha','synthetic',6))

    def test_S11_production_block(self):
        self.ready()
        with self.assertRaisesRegex(Denied,'PRODUCTION_ACTIVATION_BLOCKED'):
            self.activate(environment='production')

    def test_S12_workspace_isolation(self):
        self.ready(); self.activate()
        self.assertFalse(self.m.allowed('TST-alpha','other',5))
        self.assertFalse(self.m.allowed('TST-alpha','synthetic',20))

    def test_audit_append_only(self):
        for statement in ('DELETE FROM audit','UPDATE audit SET actor="other"'):
            with self.assertRaises(sqlite3.IntegrityError): self.m.db.execute(statement)

if __name__ == '__main__': unittest.main()
