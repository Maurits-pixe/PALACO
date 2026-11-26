"""GO-20 v63: chained custody histories, independent fork and retention tests."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_head_custody_succession import SCHEMA, PIN_SCHEMA, HEAD_SCHEMA, ZERO, assess
from test_pr_head_succession_custody import SuccessionCustodyTests


class InvalidHistoryTests(unittest.TestCase):
    def test_missing_all_hold_deny(self):
        v = assess(None, None, None, None, None)
        self.assertFalse(v["custody_succession_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))


class CustodyHistoryTests(unittest.TestCase):
    def setUp(self):
        base = SuccessionCustodyTests("test_complete_archive_evidence_still_deny")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        source = {
            "v61_sources": base.sources, "copies": base.copies,
            "trust": base.trust, "independent_pin": base.pin,
        }
        first = {"snapshot": 50, "previous_sha256": ZERO,
                 "sources": copy.deepcopy(source)}
        second = {"snapshot": 51, "previous_sha256": canonical_hash(first),
                  "sources": copy.deepcopy(source)}
        self.left = {"schema": SCHEMA, "snapshots": [first, second]}
        self.right = copy.deepcopy(self.left)
        self.left_pin = self.repin(self.left)
        self.right_pin = self.repin(self.right)
        self.head = {
            "schema": HEAD_SCHEMA,
            "expected_history_sha256": canonical_hash(self.left),
            "minimum_last_snapshot": 51,
            "minimum_receipts": 2, "minimum_round": 41,
        }

    def repin(self, view):
        source = view["snapshots"][0]["sources"]
        return {
            "schema": PIN_SCHEMA,
            "first_snapshot": 50, "last_snapshot": 51,
            "first_sha256": canonical_hash(view["snapshots"][0]),
            "last_sha256": canonical_hash(view["snapshots"][-1]),
            "history_sha256": canonical_hash(view),
            "v61_sources_sha256": canonical_hash(source["v61_sources"]),
            "trust_sha256": canonical_hash(source["trust"]),
            "minimum_receipts": 2, "minimum_round": 41,
        }

    def check(self):
        return assess(self.left, self.left_pin, self.right, self.right_pin, self.head)

    def test_matching_history_still_deny(self):
        v = self.check()
        self.assertTrue(v["custody_succession_valid"], v["errors"])
        self.assertEqual(v["snapshots_verified"], 4)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for k in ("remote_publication_verified", "storage_reachability_verified",
                  "independent_media_custody_verified", "history_restored",
                  "recovery_authorized", "failover_authorized",
                  "merge_authorized", "deployment_authorized",
                  "production_commit_performed"):
            self.assertFalse(v[k])

    def test_missing_snapshot(self):
        self.right["snapshots"].pop()
        self.assertIn("right:invalid_custody_history", self.check()["errors"])

    def test_skipped_snapshot(self):
        self.right["snapshots"][1]["snapshot"] = 52
        self.assertIn("right:invalid_or_missing_snapshot:1", self.check()["errors"])

    def test_corrupted_link_after_repinned(self):
        self.right["snapshots"][1]["previous_sha256"] = "f"*64
        self.right_pin = self.repin(self.right)
        self.assertIn("right:broken_snapshot_link:1", self.check()["errors"])

    def test_corrupted_genesis(self):
        self.left["snapshots"][0]["previous_sha256"] = "f"*64
        self.assertIn("left:invalid_genesis_link", self.check()["errors"])

    def test_wrong_first_anchor(self):
        self.left_pin["first_sha256"] = "f"*64
        self.assertIn("left:first_snapshot_anchor_mismatch", self.check()["errors"])

    def test_wrong_last_anchor(self):
        self.right_pin["last_sha256"] = "f"*64
        self.assertIn("right:last_snapshot_anchor_mismatch", self.check()["errors"])

    def test_wrong_history_anchor(self):
        self.right_pin["history_sha256"] = "f"*64
        self.assertIn("right:independent_custody_history_anchor_mismatch", self.check()["errors"])

    def test_custodian_key_replacement(self):
        self.right["snapshots"][1]["sources"]["trust"]["members"]["archive-a"]["public_key_hex"] = "f"*64
        self.assertIn("right:external_trust_or_history_substitution:1", self.check()["errors"])

    def test_original_v61_evidence_replaced(self):
        self.right["snapshots"][1]["sources"]["v61_sources"]["right"]["rounds"].pop()
        self.assertIn("right:external_trust_or_history_substitution:1", self.check()["errors"])

    def test_forged_v62_custody_receipt(self):
        self.right["snapshots"][1]["sources"]["copies"]["rounds"][0]["receipts"][0]["signature_ed25519_hex"] = "0"*128
        self.assertTrue(any(x.startswith("right:v62:1:") for x in self.check()["errors"]))

    def test_conflicting_receipt_order_between_snapshots(self):
        second = self.right["snapshots"][1]
        second["sources"]["copies"]["rounds"][0]["receipts"].reverse()
        second["sources"]["independent_pin"]["copies_sha256"] = canonical_hash(second["sources"]["copies"])
        self.right_pin = self.repin(self.right)
        self.assertIn("right:conflicting_historical_receipt_register:1", self.check()["errors"])

    def test_validly_signed_but_differing_observer_archives(self):
        # Reordering signatures preserves individual v62 validity.
        for snapshot in self.right["snapshots"]:
            snapshot["sources"]["copies"]["rounds"][0]["receipts"].reverse()
            snapshot["sources"]["independent_pin"]["copies_sha256"] = canonical_hash(
                snapshot["sources"]["copies"])
        self.right["snapshots"][1]["previous_sha256"] = canonical_hash(self.right["snapshots"][0])
        self.right_pin = self.repin(self.right)
        v = self.check()
        self.assertIn("contradictory_archival_receipt_histories", v["errors"])
        self.assertIn("right_external_head_mismatch", v["errors"])

    def test_external_minimum_snapshot(self):
        self.head["minimum_last_snapshot"] = 52
        self.assertIn("independent_snapshot_rollback", self.check()["errors"])

    def test_external_receipt_quorum_floor(self):
        self.head["minimum_receipts"] = 3
        self.assertIn("external_retention_or_quorum_downgrade", self.check()["errors"])

    def test_external_round_floor(self):
        self.head["minimum_round"] = 42
        self.assertIn("external_retention_or_quorum_downgrade", self.check()["errors"])

    def test_bool_receipt_floor(self):
        self.left_pin["minimum_receipts"] = True
        self.assertIn("left:invalid_custody_history_pin", self.check()["errors"])

    def test_bool_head_floor(self):
        self.head["minimum_last_snapshot"] = True
        self.assertIn("invalid_independent_head", self.check()["errors"])

    def test_missing_receipts_in_original(self):
        self.right["snapshots"][1]["sources"]["copies"]["rounds"][0]["receipts"].pop()
        self.assertFalse(self.check()["custody_succession_valid"])

    def test_replay_prior_round_signature(self):
        evidence = self.right["snapshots"][1]["sources"]
        evidence["copies"]["rounds"][1]["receipts"][0]["signature_ed25519_hex"] = (
            evidence["copies"]["rounds"][0]["receipts"][0]["signature_ed25519_hex"])
        evidence["independent_pin"]["copies_sha256"] = canonical_hash(evidence["copies"])
        self.assertTrue(any(x.startswith("right:v62:1:") for x in self.check()["errors"]))


if __name__ == "__main__":
    unittest.main()
