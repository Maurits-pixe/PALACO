"""GO-20 v34: offline segmented restoration and atomicity regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_recovery_simulation import (
    SCHEMA, MANIFEST_SCHEMA, PIN_SCHEMA, simulate,
)
from test_pr_observer_recovery import RecoveryTests


class MissingSegmentsTests(unittest.TestCase):
    def test_all_missing_denied(self):
        v = simulate(None, None, None)
        self.assertFalse(v["simulation_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["restore_performed"])

    def test_nonjson_rejected(self):
        v = simulate({"bad": {1, 2}}, None, None)
        self.assertFalse(v["simulation_valid"])


class SegmentedRestoreTests(unittest.TestCase):
    def setUp(self):
        base = RecoveryTests("test_valid_recovered_history_remains_hold")
        base.setUp()
        self.base = base
        parts = {
            **{f"epoch:{i}": copy.deepcopy(e)
               for i, e in enumerate(base.history["epochs"])},
            "rotations": copy.deepcopy(base.history["rotations"]),
            "v32_pin": copy.deepcopy(base.v32_pin),
            "revocations": copy.deepcopy(base.revocations),
            "inventory": copy.deepcopy(base.inventory),
            "recovery_pin": copy.deepcopy(base.pin),
        }
        self.package = {"schema": SCHEMA, "parts": [
            {"name": name, "content": content} for name, content in parts.items()
        ]}
        self.manifest = {
            "schema": MANIFEST_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "epoch_count": 2,
            "history_sha256": canonical_hash(base.history),
            "segment_sha256": {
                name: canonical_hash(content) for name, content in parts.items()
            },
        }
        self.pin = {
            "schema": PIN_SCHEMA, "expected_epochs": 2,
            "manifest_sha256": canonical_hash(self.manifest),
        }

    def check(self):
        return simulate(self.package, self.manifest, self.pin)

    def test_complete_memory_only_restore_verifies(self):
        v = self.check()
        self.assertTrue(v["simulation_valid"], v["errors"])
        self.assertTrue(v["recovery_evidence_valid"])
        self.assertEqual(v["segments_verified"], 7)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["restore_performed"])
        self.assertFalse(v["write_performed"])

    def test_unordered_fragments_reconstruct(self):
        self.package["parts"].reverse()
        self.assertTrue(self.check()["simulation_valid"], self.check()["errors"])

    def test_missing_middle_epoch_rejected(self):
        self.package["parts"] = [
            p for p in self.package["parts"] if p["name"] != "epoch:1"
        ]
        self.assertFalse(self.check()["simulation_valid"])

    def test_missing_rotation_ledger_rejected(self):
        self.package["parts"] = [
            p for p in self.package["parts"] if p["name"] != "rotations"
        ]
        self.assertFalse(self.check()["simulation_valid"])

    def test_duplicate_fragment_denied(self):
        self.package["parts"][-1] = copy.deepcopy(self.package["parts"][0])
        self.assertFalse(self.check()["simulation_valid"])

    def test_modified_snapshot_without_manifest_update(self):
        self.package["parts"][0]["content"]["epoch"] = 999
        self.assertIn("segment_digest_mismatch:epoch:0", self.check()["errors"])

    def test_modified_snapshot_even_with_rehashed_manifest(self):
        self.package["parts"][0]["content"]["epoch"] = 999
        self.manifest["segment_sha256"]["epoch:0"] = canonical_hash(
            self.package["parts"][0]["content"]
        )
        self.pin["manifest_sha256"] = canonical_hash(self.manifest)
        self.assertIn("reconstructed_history_mismatch", self.check()["errors"])

    def test_revocation_fragment_modified(self):
        item = next(p for p in self.package["parts"] if p["name"] == "revocations")
        item["content"]["entries"].append({
            "public_key_hex": "a" * 64, "effective_epoch": 8,
        })
        self.assertIn("segment_digest_mismatch:revocations", self.check()["errors"])

    def test_independent_manifest_replaced(self):
        self.pin["manifest_sha256"] = "0" * 64
        self.assertIn("independent_manifest_mismatch", self.check()["errors"])

    def test_forged_retention_epoch_count(self):
        self.pin["expected_epochs"] = 3
        self.assertIn("invalid_independent_manifest_pin", self.check()["errors"])

    def test_unknown_fragment_denied(self):
        self.package["parts"][0]["name"] = "epoch:100"
        self.assertFalse(self.check()["simulation_valid"])

    def test_source_history_rollback(self):
        for part in self.package["parts"]:
            if part["name"] == "epoch:1":
                part["content"] = copy.deepcopy(
                    next(p["content"] for p in self.package["parts"]
                         if p["name"] == "epoch:0"))
        self.assertFalse(self.check()["simulation_valid"])

    def test_rotations_must_be_present_even_if_empty(self):
        item = next(p for p in self.package["parts"] if p["name"] == "rotations")
        item["content"] = None
        self.assertFalse(self.check()["simulation_valid"])

    def test_wrong_repository_rejected(self):
        self.manifest["repository"] = "attacker/project"
        self.pin["manifest_sha256"] = canonical_hash(self.manifest)
        self.assertIn("invalid_recovery_manifest", self.check()["errors"])

    def test_zero_authority_on_corrupt_backup(self):
        self.package["parts"][0]["content"] = []
        v = self.check()
        self.assertFalse(v["simulation_valid"])
        for key in ("release_authorized", "merge_authorized",
                    "deployment_authorized", "restore_performed", "write_performed"):
            self.assertFalse(v[key])


if __name__ == "__main__":
    unittest.main()
