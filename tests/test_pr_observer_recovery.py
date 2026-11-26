"""GO-20 v33: retained checkpoints and restored historical evidence regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import ZERO, canonical_hash
from pr_observer_recovery import (
    SCHEMA, PIN_SCHEMA, CHECKPOINT_SCHEMA, verify_recovery,
)
from test_pr_observer_anchor_history import HistoricalObserverTests


class MissingRecoveryTests(unittest.TestCase):
    def test_missing_all_sources_fail_closed(self):
        v = verify_recovery(None, None, None, None, None)
        self.assertFalse(v["recovery_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["restore_performed"])

    def test_nonjson_data_rejected(self):
        v = verify_recovery({"epochs": {1, 2}}, None, None, None, None)
        self.assertFalse(v["recovery_evidence_valid"])


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        base = HistoricalObserverTests("test_two_valid_epoch_snapshots_hold_deny")
        base.setUp()
        self.history = base.history
        self.v32_pin = base.pin
        self.revocations = base.revocations
        self.inventory = self.make_inventory()
        self.pin = self.make_pin()

    def make_inventory(self):
        previous = ZERO
        checkpoints = []
        for epoch in self.history["epochs"]:
            statement = {
                "schema": CHECKPOINT_SCHEMA, "epoch": epoch["epoch"],
                "snapshot_sha256": canonical_hash(epoch),
                "previous_checkpoint_sha256": previous,
            }
            digest = canonical_hash(statement)
            checkpoints.append({**statement, "checkpoint_sha256": digest})
            previous = digest
        return {
            "schema": SCHEMA, "repository": "Maurits-pixe/PALACO",
            "checkpoints": checkpoints,
            "history_sha256": canonical_hash(self.history),
            "v32_pin_sha256": canonical_hash(self.v32_pin),
            "revocations_sha256": canonical_hash(self.revocations),
        }

    def make_pin(self):
        return {
            "schema": PIN_SCHEMA,
            "inventory_sha256": canonical_hash(self.inventory),
            "first_checkpoint_sha256": self.inventory["checkpoints"][0]["checkpoint_sha256"],
            "last_checkpoint_sha256": self.inventory["checkpoints"][-1]["checkpoint_sha256"],
            "minimum_epochs": 2,
            "last_epoch": 8,
        }

    def check(self):
        return verify_recovery(self.history, self.v32_pin, self.revocations,
                               self.inventory, self.pin)

    def test_valid_recovered_history_remains_hold(self):
        v = self.check()
        self.assertTrue(v["recovery_evidence_valid"], v["errors"])
        self.assertTrue(v["historical_chain_valid"])
        self.assertEqual(v["checkpoints_verified"], 2)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for key in ("restore_performed", "release_authorized", "merge_authorized",
                    "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[key])

    def test_tampered_recovered_snapshot(self):
        self.history["epochs"][0]["independent_heads"]["heads"]["observer-a"]["minimum_epoch"] = 0
        self.assertIn("restored_history_mismatch", self.check()["errors"])

    def test_missing_history_epoch(self):
        self.history["epochs"].pop()
        self.assertFalse(self.check()["recovery_evidence_valid"])

    def test_out_of_order_checkpoints(self):
        self.inventory["checkpoints"].reverse()
        self.pin = self.make_pin()
        self.assertTrue(any(e.startswith("checkpoint_integrity_failure:")
                            for e in self.check()["errors"]))

    def test_middle_checkpoint_tampered(self):
        self.inventory["checkpoints"][1]["snapshot_sha256"] = "a" * 64
        self.pin = self.make_pin()
        self.assertIn("checkpoint_integrity_failure:1", self.check()["errors"])

    def test_rollback_floor(self):
        self.pin["last_epoch"] = 7
        self.assertIn("recovery_epoch_rollback", self.check()["errors"])

    def test_minimum_retention_floor(self):
        self.pin["minimum_epochs"] = 3
        self.assertIn("invalid_retention_floor_or_anchor", self.check()["errors"])

    def test_replaced_independent_inventory(self):
        self.pin["inventory_sha256"] = "a" * 64
        self.assertIn("independent_inventory_mismatch", self.check()["errors"])

    def test_changed_revocations(self):
        self.revocations["entries"].append({
            "public_key_hex": "a" * 64, "effective_epoch": 7})
        self.assertIn("revocations_mismatch", self.check()["errors"])

    def test_changed_governance_pin(self):
        self.v32_pin["last_snapshot_sha256"] = ZERO
        self.assertIn("v32_pin_mismatch", self.check()["errors"])

    def test_unpinned_first_checkpoint(self):
        self.pin["first_checkpoint_sha256"] = ZERO
        self.assertIn("first_checkpoint_anchor_mismatch", self.check()["errors"])

    def test_unpinned_last_checkpoint(self):
        self.pin["last_checkpoint_sha256"] = ZERO
        self.assertIn("last_checkpoint_anchor_mismatch", self.check()["errors"])

    def test_incomplete_checkpoint_list(self):
        self.inventory["checkpoints"].pop()
        self.assertIn("invalid_checkpoint_inventory", self.check()["errors"])

    def test_untrusted_repository(self):
        self.inventory["repository"] = "attacker/repo"
        self.pin = self.make_pin()
        self.assertIn("repository_mismatch", self.check()["errors"])

    def test_unauthorized_release_never_enabled(self):
        self.inventory["checkpoints"][0]["checkpoint_sha256"] = ZERO
        v = self.check()
        self.assertFalse(v["recovery_evidence_valid"])
        self.assertFalse(v["release_authorized"])
        self.assertEqual(v["authorization"], "DENY")


if __name__ == "__main__":
    unittest.main()
