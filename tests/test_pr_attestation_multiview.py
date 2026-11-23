"""GO-20 v30: conflicting signed views, shared prefixes and rotation tests."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_attestation_multiview import (
    SCHEMA, PIN_SCHEMA, examine_views,
)
from test_pr_final_attestation_history import FullHistoryTests


class InvalidViews(unittest.TestCase):
    def test_missing_package(self):
        out = examine_views(None, None)
        self.assertFalse(out["views_valid"])
        self.assertEqual((out["decision"], out["authorization"]), ("HOLD", "DENY"))

    def test_missing_pins(self):
        package = {"schema": SCHEMA, "views": [{}, {}]}
        self.assertIn("invalid_independent_multiview_pin",
                      examine_views(package, None)["errors"])


class MultiViewTests(unittest.TestCase):
    def setUp(self):
        f = FullHistoryTests("test_genesis_remains_hold_deny")
        f.setUp()
        self.fixture = f
        f.add_same_signer()
        self.first_history = copy.deepcopy(f.history)
        self.first_trust = copy.deepcopy(f.trust)
        self.first_pin = copy.deepcopy(f.pin)
        self.package = {"schema": SCHEMA, "views": [
            {"view_id": "observer-a", "history": copy.deepcopy(self.first_history),
             "custodian_trust": copy.deepcopy(self.first_trust)},
            {"view_id": "observer-b", "history": copy.deepcopy(self.first_history),
             "custodian_trust": copy.deepcopy(self.first_trust)},
        ]}
        self.pins = {"schema": PIN_SCHEMA, "views": {
            "observer-a": copy.deepcopy(self.first_pin),
            "observer-b": copy.deepcopy(self.first_pin),
        }}

    def check(self):
        return examine_views(self.package, self.pins)

    def test_identical_verified_histories_stay_hold(self):
        v = self.check()
        self.assertTrue(v["views_valid"], v["errors"])
        self.assertEqual(v["views_checked"], 2)
        self.assertFalse(v["fork_detected"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for name in ("release_authorized", "merge_authorized",
                     "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[name])

    def test_valid_prefix_view_allowed(self):
        view = self.package["views"][1]
        view["history"]["entries"].pop()
        self.pins["views"]["observer-b"]["last_sequence"] = 0
        self.pins["views"]["observer-b"]["last_attestation_sha256"] = canonical_hash(
            view["history"]["entries"][0]["envelope"])
        self.assertTrue(self.check()["views_valid"], self.check()["errors"])

    def test_two_valid_signed_branches_detected(self):
        f = self.fixture
        # Retain the same genesis but replace the second publication with a
        # separately signed and dual-authorized custodian rotation.
        f.entries.pop()
        f.add_rotated_signer()
        self.package["views"][1]["history"] = copy.deepcopy(f.history)
        self.package["views"][1]["custodian_trust"] = copy.deepcopy(f.trust)
        self.pins["views"]["observer-b"] = copy.deepcopy(f.pin)
        v = self.check()
        self.assertTrue(v["fork_detected"], v["errors"])
        self.assertIn("conflicting_signed_attestations", v["errors"])
        self.assertEqual(v["fork_sequences"], [1])
        self.assertEqual(v["rotation_records_checked"], 1)

    def test_tampered_history_rejected_before_comparison(self):
        self.package["views"][1]["history"]["entries"][1][
            "envelope"]["signature_ed25519_hex"] = "0" * 128
        self.assertFalse(self.check()["views_valid"])
        self.assertTrue(any(e.startswith("view:observer-b:") for e in self.check()["errors"]))

    def test_missing_independent_observer_pin(self):
        del self.pins["views"]["observer-b"]
        self.assertIn("independent_view_pin_coverage_mismatch", self.check()["errors"])

    def test_duplicate_observer_id_rejected(self):
        self.package["views"][1]["view_id"] = "observer-a"
        self.assertIn("duplicate_or_invalid_view_identity", self.check()["errors"])

    def test_conflicting_signer_key_registry(self):
        self.package["views"][1]["custodian_trust"]["keys"][
            "report-custodian"]["public_key_hex"] = "a" * 64
        self.assertFalse(self.check()["views_valid"])

    def test_invalid_rotation_signature_in_second_view(self):
        f = self.fixture
        f.entries.pop()
        f.add_rotated_signer()
        f.history["rotations"][0]["new_signature_ed25519_hex"] = "0" * 128
        self.package["views"][1]["history"] = f.history
        self.package["views"][1]["custodian_trust"] = f.trust
        self.pins["views"]["observer-b"] = f.pin
        self.assertFalse(self.check()["views_valid"])

    def test_observer_rollback_against_pin(self):
        self.package["views"][1]["history"]["entries"].pop()
        self.assertFalse(self.check()["views_valid"])

    def test_malformed_observer_history(self):
        self.package["views"][1]["history"] = ["invalid"]
        self.assertFalse(self.check()["views_valid"])

    def test_non_json_payload_rejected(self):
        self.package["views"][1]["custodian_trust"] = {"bad": {1, 2}}
        self.assertFalse(self.check()["views_valid"])


if __name__ == "__main__":
    unittest.main()
