from tempfile import TemporaryDirectory
import unittest
from rehearsal import Rehearsal, run


class IntegratedTests(unittest.TestCase):
    def setUp(self):
        tmp=TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.f=Rehearsal(tmp.name)
        self.addCleanup(self.f.close)

    def activate(self):
        self.f.approve_start()
        self.assertEqual(self.f.request('reviews')[0],200)
        self.assertEqual(self.f.request('activations')[0],200)

    def test_full_rehearsal_passes_with_bounded_claims(self):
        result=run()
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(len(result['checks']),15)
        self.assertTrue(all(value is True for value in result['checks'].values()))
        self.assertEqual(result['rioRuntimeIntegration'],'NOT_EXECUTED')
        self.assertEqual(result['production'],'HOLD')

    def test_unapproved_boot_never_reaches_review(self):
        self.assertEqual(self.f.request('reviews')[0],403)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],'SAFETY_REVIEW_PENDING')
        self.assertFalse(self.f.active())

    def test_revoked_session_blocks_activation_through_all_layers(self):
        self.f.approve_start()
        self.assertEqual(self.f.request('reviews')[0],200)
        self.f.sessions.revoke(self.f.credentials['TST-activator'][0])
        self.assertEqual(self.f.request('activations')[0],401)
        self.assertEqual(self.f.model.get('TST-alpha')['state'],'APPROVED_FOR_ACTIVATION')
        self.assertFalse(self.f.active())

    def test_boot_expiry_blocks_request_despite_valid_session(self):
        self.f.approve_start()
        self.f.now=23
        self.assertEqual(self.f.request('reviews')[0],403)
        self.assertFalse(self.f.active())

    def test_storage_failure_is_denied_at_adapter_and_access(self):
        self.activate()
        self.f.model.db.close()
        self.assertEqual(self.f.request('activations')[0],403)
        self.assertFalse(self.f.active())
        self.assertEqual(self.f.safety.db.execute('SELECT state FROM circuit').fetchone()[0],'LOCKED')

    def test_restart_requires_new_approval_for_adapter(self):
        self.activate(); self.f.restart()
        self.assertEqual(self.f.request('activations')[0],403)
        self.f.approve_start()
        self.assertEqual(self.f.request('activations')[0],200)
        self.assertTrue(self.f.active())

    def test_client_cannot_select_inner_guard_or_production(self):
        self.f.approve_start()
        self.assertEqual(self.f.request('reviews',environment='production')[0],400)
        self.assertEqual(self.f.request('reviews',guard='Model')[0],400)
        self.assertFalse(self.f.active())

if __name__=='__main__': unittest.main()
