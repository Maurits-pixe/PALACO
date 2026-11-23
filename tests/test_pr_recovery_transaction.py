"""GO-20 v35: isolated transaction atomicity and rollback regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_recovery_transaction import execute_sandbox
from test_pr_recovery_simulation import SegmentedRestoreTests


class InvalidSandboxTests(unittest.TestCase):
    def test_missing_evidence_fails_closed(self):
        v = execute_sandbox(None, None, None)
        self.assertFalse(v["transaction_valid"])
        self.assertFalse(v["production_write_performed"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_unknown_fault_point_denied(self):
        v = execute_sandbox(None, None, None, "after_prod_write")
        self.assertIn("invalid_fault_point", v["errors"])

    def test_untrusted_nonjson_evidence_denied(self):
        self.assertFalse(execute_sandbox({"test": {3, 4}}, None, None)["transaction_valid"])


class TransactionTests(unittest.TestCase):
    def setUp(self):
        f = SegmentedRestoreTests("test_complete_memory_only_restore_verifies")
        f.setUp()
        self.package, self.manifest, self.pin = f.package, f.manifest, f.pin

    def call(self, fault="none"):
        return execute_sandbox(self.package, self.manifest, self.pin, fault)

    def test_valid_sandbox_commit_never_authorizes_release(self):
        v = self.call()
        self.assertTrue(v["transaction_valid"], v["errors"])
        self.assertEqual(v["expected_segments"], 7)
        self.assertEqual(v["sandbox_rows_after_transaction"], 7)
        self.assertTrue(v["sandbox_commit_performed"])
        self.assertFalse(v["restore_performed"])
        self.assertFalse(v["production_commit_performed"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_injected_after_begin_rolls_back(self):
        v = self.call("after_begin")
        self.assertTrue(v["rollback_verified"], v["errors"])
        self.assertEqual(v["sandbox_rows_after_transaction"], 0)
        self.assertFalse(v["sandbox_commit_performed"])
        self.assertFalse(v["transaction_valid"])

    def test_injected_after_first_fragment_rolls_back(self):
        v = self.call("after_first_segment")
        self.assertTrue(v["rollback_verified"], v["errors"])
        self.assertEqual(v["sandbox_rows_after_transaction"], 0)
        self.assertFalse(v["production_write_performed"])

    def test_injected_before_commit_rolls_back_every_row(self):
        v = self.call("before_commit")
        self.assertTrue(v["rollback_verified"], v["errors"])
        self.assertEqual(v["sandbox_rows_after_transaction"], 0)
        self.assertFalse(v["transaction_valid"])

    def test_missing_restore_fragment_no_transaction(self):
        self.package["parts"].pop()
        v = self.call()
        self.assertFalse(v["transaction_valid"])
        self.assertEqual(v["sandbox_rows_after_transaction"], 0)
        self.assertFalse(v["sandbox_commit_performed"])

    def test_duplicate_restore_fragment_rejected(self):
        self.package["parts"][-1] = copy.deepcopy(self.package["parts"][0])
        self.assertFalse(self.call()["transaction_valid"])

    def test_manifest_tampering_denied_before_transaction(self):
        self.manifest["history_sha256"] = "a" * 64
        self.assertFalse(self.call()["transaction_valid"])

    def test_external_pin_rollback_denied(self):
        self.pin["expected_epochs"] = 1
        self.assertFalse(self.call()["transaction_valid"])

    def test_corrupted_epoch_fragment_denied(self):
        item = next(x for x in self.package["parts"] if x["name"] == "epoch:0")
        item["content"]["epoch"] = 500
        self.assertFalse(self.call()["transaction_valid"])

    def test_arbitrary_fragment_order_is_allowed(self):
        self.package["parts"].reverse()
        v = self.call()
        self.assertTrue(v["transaction_valid"], v["errors"])
        self.assertEqual(v["sandbox_rows_after_transaction"], 7)

    def test_empty_rotation_segment_valid_with_baseline(self):
        v = self.call()
        self.assertTrue(v["transaction_valid"], v["errors"])
        rotation = next(x for x in self.package["parts"] if x["name"] == "rotations")
        self.assertEqual(rotation["content"], [])

    def test_postfault_fresh_run_succeeds_without_residual_data(self):
        first = self.call("after_first_segment")
        second = self.call()
        self.assertTrue(first["rollback_verified"])
        self.assertTrue(second["transaction_valid"], second["errors"])
        self.assertEqual(second["sandbox_rows_after_transaction"], 7)

    def test_error_never_grants_authority(self):
        v = self.call("before_commit")
        for name in ("release_authorized", "merge_authorized",
                     "deployment_authorized", "production_commit_performed",
                     "production_write_performed", "restore_performed"):
            self.assertFalse(v[name])

    def test_changed_revocation_segment_denied(self):
        part = next(x for x in self.package["parts"] if x["name"] == "revocations")
        part["content"]["entries"].append(
            {"public_key_hex": "b" * 64, "effective_epoch": 8})
        self.assertFalse(self.call()["transaction_valid"])

    def test_rehashed_manifest_without_independent_pin_denied(self):
        part = self.package["parts"][0]
        part["content"]["epoch"] = 400
        self.manifest["segment_sha256"][part["name"]] = canonical_hash(part["content"])
        self.assertFalse(self.call()["transaction_valid"])


if __name__ == "__main__":
    unittest.main()
