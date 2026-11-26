"""GO-20 v26: hostile input and governance hardening regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_governance_hardening import harden, validate_shape
from test_pr_governance_history import GovernanceHistoryTests


class HardeningInputTests(unittest.TestCase):
    def test_none_fails_closed(self):
        v = harden(None, None, None)
        self.assertFalse(v["evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_non_json_set_fails_closed(self):
        self.assertFalse(harden({"a": {1, 2}}, None, None)["evidence_valid"])

    def test_non_json_float_fails_closed(self):
        self.assertFalse(harden({"number": 1.5}, None, None)["evidence_valid"])

    def test_nested_depth_bound(self):
        value = "end"
        for _ in range(70):
            value = [value]
        with self.assertRaisesRegex(ValueError, "depth_limit"):
            validate_shape(value)

    def test_wide_evidence_bound(self):
        with self.assertRaisesRegex(ValueError, "list_limit"):
            validate_shape([None] * 250001)

    def test_long_string_bound(self):
        with self.assertRaisesRegex(ValueError, "string_limit"):
            validate_shape("x" * 1000001)


class HardenedGovernanceTests(unittest.TestCase):
    def setUp(self):
        fixture = GovernanceHistoryTests("test_valid_unchanged_history_still_denies")
        fixture.setUp()
        self.history, self.pin, self.trust = fixture.history, fixture.pin, fixture.trust

    def check(self):
        return harden(self.history, self.pin, self.trust)

    def test_valid_governance_stays_denied(self):
        v = self.check()
        self.assertTrue(v["evidence_valid"], v["errors"])
        for name in ("release_authorized", "merge_authorized",
                     "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[name])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_corrupted_transition_declaration_list(self):
        self.history["transitions"][0]["changed_roles"] = [{"unsafe": True}]
        self.assertFalse(self.check()["evidence_valid"])

    def test_corrupted_trust_record_value(self):
        self.history["snapshots"][0]["reviewer_trust"]["reviewers"] = [7, 8]
        self.assertFalse(self.check()["evidence_valid"])

    def test_corrupted_review_attestations(self):
        self.history["snapshots"][0]["review"]["attestations"] = {"not": "a list"}
        self.assertFalse(self.check()["evidence_valid"])

    def test_corrupted_snapshot_roster(self):
        self.history["snapshots"][1]["policy"]["reviewers"] = {"evidence_reviewer": []}
        self.assertFalse(self.check()["evidence_valid"])

    def test_history_snapshot_deleted(self):
        self.history["snapshots"].pop()
        self.assertFalse(self.check()["evidence_valid"])

    def test_historical_pin_substituted(self):
        self.pin["first_policy_sha256"] = "a" * 64
        self.assertFalse(self.check()["evidence_valid"])

    def test_controller_registry_revoked(self):
        self.trust["controllers"]["governance-controller"]["status"] = "revoked"
        self.assertFalse(self.check()["evidence_valid"])

    def test_governance_release_prohibition_removed(self):
        self.history["snapshots"][1]["policy"]["prohibited_capabilities"].remove("merge")
        self.assertFalse(self.check()["evidence_valid"])

    def test_duplicate_revision_bool_rejected(self):
        self.history["snapshots"][1]["policy"]["revision"] = True
        self.assertFalse(self.check()["evidence_valid"])


if __name__ == "__main__":
    unittest.main()
