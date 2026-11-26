"""GO-20 v59: historical reconstruction review continuity regressions."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_reconstruction_review_history import SCHEMA, PIN_SCHEMA, HEAD_SCHEMA, ZERO, assess
from test_pr_isolated_evidence_reconstruction import ReconstructionTests


class InvalidHistoryTests(unittest.TestCase):
    def test_missing_evidence_remains_hold_deny(self):
        result = assess(None, None, None, None, None)
        self.assertFalse(result["review_history_valid"])
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))


class ReviewHistoryTests(unittest.TestCase):
    def setUp(self):
        source = ReconstructionTests("test_complete_memory_reconstruction_still_deny")
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.source = source
        evidence = {
            "v57": source.v57,
            "reconstruction": source.reconstruction,
            "reviewers": source.trust,
            "pin": source.pin,
            "observed_at": 120,
        }
        first = {"round": 30, "previous_round_sha256": ZERO,
                 "sources": copy.deepcopy(evidence)}
        second = {"round": 31, "previous_round_sha256": canonical_hash(first),
                  "sources": copy.deepcopy(evidence)}
        self.left = {"schema": SCHEMA, "rounds": [first, second]}
        self.right = copy.deepcopy(self.left)
        self.pin_left = self.repin(self.left)
        self.pin_right = self.repin(self.right)
        self.head = {
            "schema": HEAD_SCHEMA,
            "expected_view_sha256": canonical_hash(self.left),
            "minimum_last_round": 31,
        }

    def repin(self, view):
        source = view["rounds"][0]["sources"]
        return {
            "schema": PIN_SCHEMA,
            "first_round": 30, "last_round": 31,
            "first_round_sha256": canonical_hash(view["rounds"][0]),
            "last_round_sha256": canonical_hash(view["rounds"][-1]),
            "view_sha256": canonical_hash(view),
            "v57_sha256": canonical_hash(source["v57"]),
            "reviewer_trust_sha256": canonical_hash(source["reviewers"]),
            "minimum_reviews": 2,
        }

    def check(self):
        return assess(self.left, self.pin_left, self.right, self.pin_right, self.head)

    def test_valid_identical_histories_still_deny(self):
        result = self.check()
        self.assertTrue(result["review_history_valid"], result["errors"])
        self.assertEqual(result["rounds_verified"], 4)
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))
        for name in ("report_promoted", "trust_registry_promoted", "history_restored",
                     "physical_media_verified", "production_restoration_performed",
                     "failover_authorized", "merge_authorized", "deployment_authorized",
                     "production_commit_performed"):
            self.assertFalse(result[name])

    def test_missing_round(self):
        self.right["rounds"].pop()
        self.assertFalse(self.check()["review_history_valid"])

    def test_skipped_round(self):
        self.right["rounds"][1]["round"] = 32
        self.assertIn("right:invalid_or_missing_round:1", self.check()["errors"])

    def test_broken_link_even_if_repinned(self):
        self.right["rounds"][1]["previous_round_sha256"] = "f"*64
        self.pin_right = self.repin(self.right)
        self.assertIn("right:broken_round_link:1", self.check()["errors"])

    def test_first_round_anchor_tamper(self):
        self.pin_left["first_round_sha256"] = "a"*64
        self.assertIn("left:first_round_anchor_mismatch", self.check()["errors"])

    def test_final_round_anchor_tamper(self):
        self.pin_left["last_round_sha256"] = "a"*64
        self.assertIn("left:last_round_anchor_mismatch", self.check()["errors"])

    def test_replaced_reviewer_key(self):
        self.right["rounds"][1]["sources"]["reviewers"]["members"]["review-a"]["public_key_hex"] = "a"*64
        self.assertIn("right:external_trust_or_evidence_substitution:1", self.check()["errors"])

    def test_changed_underlying_v57_archive(self):
        self.right["rounds"][1]["sources"]["v57"]["challenges"]["epochs"][0]["nonce_sha256"] = "a"*64
        self.assertIn("right:external_trust_or_evidence_substitution:1", self.check()["errors"])

    def test_deleted_reconstruction_copy(self):
        self.right["rounds"][1]["sources"]["reconstruction"]["epochs"][0]["copies"].pop()
        self.assertFalse(self.check()["review_history_valid"])

    def test_replayed_forged_reviewer_signature(self):
        self.right["rounds"][1]["sources"]["reconstruction"]["review_signatures"][0]["signature_ed25519_hex"] = "0"*128
        self.assertTrue(any(e.startswith("right:v58:1:") for e in self.check()["errors"]))

    def test_rollback_minimum_round(self):
        self.head["minimum_last_round"] = 32
        self.assertIn("review_history_rollback", self.check()["errors"])

    def test_independent_view_anchor(self):
        self.pin_right["view_sha256"] = "f"*64
        self.assertIn("right:external_review_history_anchor_mismatch", self.check()["errors"])

    def test_wrong_external_head(self):
        self.head["expected_view_sha256"] = "f"*64
        self.assertIn("left_external_head_mismatch", self.check()["errors"])

    def test_boolean_minimum_review(self):
        self.pin_left["minimum_reviews"] = True
        self.assertIn("left:invalid_review_history_pin", self.check()["errors"])

    def test_boolean_minimum_head(self):
        self.head["minimum_last_round"] = True
        self.assertIn("invalid_independent_head", self.check()["errors"])

    def test_independently_valid_divergent_report_histories(self):
        # Both histories have complete v58 evidence. Change the second
        # observer's review signature order for both rounds, keeping the
        # original signed statements valid and rebuilding the chain links.
        self.right["rounds"][0]["sources"]["reconstruction"]["review_signatures"].reverse()
        self.right["rounds"][1]["sources"]["reconstruction"]["review_signatures"].reverse()
        self.right["rounds"][1]["previous_round_sha256"] = canonical_hash(self.right["rounds"][0])
        self.pin_right = self.repin(self.right)
        result = self.check()
        self.assertIn("contradictory_reconstruction_reports", result["errors"])
        self.assertIn("right_external_head_mismatch", result["errors"])

    def test_cannot_rewrite_report_during_history(self):
        self.right["rounds"][1]["sources"]["reconstruction"]["review_signatures"].reverse()
        self.right["rounds"][1]["previous_round_sha256"] = canonical_hash(self.right["rounds"][0])
        self.pin_right = self.repin(self.right)
        self.assertIn("right:conflicting_reconstruction_results:1", self.check()["errors"])

    def test_original_v57_expiry(self):
        self.right["rounds"][1]["sources"]["observed_at"] = 151
        self.assertFalse(self.check()["review_history_valid"])

    def test_weakening_review_quorum_denied(self):
        self.right["rounds"][1]["sources"]["pin"]["minimum_reviews"] = 1
        self.assertFalse(self.check()["review_history_valid"])


if __name__ == "__main__":
    unittest.main()
