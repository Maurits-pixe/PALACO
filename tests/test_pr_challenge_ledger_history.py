"""GO-20 v51: signed historical ledger checkpoint continuity and fork tests."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_challenge_ledger_history import SCHEMA, PIN_SCHEMA, assess
from test_pr_challenge_ledger_checkpoint import LedgerCheckpointTests


class InvalidHistoryTests(unittest.TestCase):
    def test_missing_sources_denied(self):
        v = assess(None, None, None, None, None)
        self.assertFalse(v["history_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))


class LedgerHistoryTests(unittest.TestCase):
    def setUp(self):
        base = LedgerCheckpointTests("test_verified_signed_snapshot_remains_hold")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        first = {
            "rows": copy.deepcopy(base.rows),
            "checkpoint": copy.deepcopy(base.checkpoint),
            "independent_pin": copy.deepcopy(base.pin),
            "signature": copy.deepcopy(base.signature),
        }
        cp = copy.deepcopy(base.checkpoint)
        cp["sequence"] = 3
        cp["previous_checkpoint_sha256"] = canonical_hash(first["checkpoint"])
        pin = copy.deepcopy(base.pin)
        pin["checkpoint_sha256"] = canonical_hash(cp)
        pin["minimum_sequence"] = 3
        base.checkpoint = cp
        second = {
            "rows": copy.deepcopy(base.rows), "checkpoint": copy.deepcopy(cp),
            "independent_pin": pin,
            "signature": {"key_id": pin["key_id"],
                          "signature_ed25519_hex": base.sign()},
        }
        self.left = {"schema": SCHEMA, "entries": [first, second]}
        self.right = copy.deepcopy(self.left)
        self.pin_left = self.make_pin(self.left)
        self.pin_right = self.make_pin(self.right)
        self.head = {
            "schema": "palaco.go20-challenge-ledger-head-pin.v1",
            "expected_history_sha256": canonical_hash(self.left),
            "minimum_last_sequence": 3,
        }

    def make_pin(self, hist):
        entries = hist["entries"]
        return {
            "schema": PIN_SCHEMA, "first_sequence": 2, "last_sequence": 3,
            "first_checkpoint_sha256": canonical_hash(entries[0]["checkpoint"]),
            "last_checkpoint_sha256": canonical_hash(entries[-1]["checkpoint"]),
            "history_sha256": canonical_hash(hist),
            "minimum_rows": 1, "minimum_consumed": 1,
        }

    def signed_second(self, hist):
        cp = hist["entries"][1]["checkpoint"]
        self.base.checkpoint = cp
        entry = hist["entries"][1]
        entry["independent_pin"]["checkpoint_sha256"] = canonical_hash(cp)
        entry["signature"]["signature_ed25519_hex"] = self.base.sign()

    def check(self):
        return assess(self.left, self.pin_left,
                      self.right, self.pin_right, self.head)

    def test_valid_two_histories_still_hold(self):
        v = self.check()
        self.assertTrue(v["history_evidence_valid"], v["errors"])
        self.assertEqual(v["checkpoints_verified"], 4)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["restoration_performed"])
        self.assertFalse(v["challenge_reopened"])

    def test_removed_checkpoint(self):
        self.right["entries"].pop()
        self.assertFalse(self.check()["history_evidence_valid"])

    def test_sequence_gap(self):
        self.right["entries"][1]["checkpoint"]["sequence"] = 4
        self.assertFalse(self.check()["history_evidence_valid"])

    def test_broken_predecessor_hash(self):
        self.right["entries"][1]["checkpoint"]["previous_checkpoint_sha256"] = "f"*64
        self.signed_second(self.right)
        self.pin_right = self.make_pin(self.right)
        self.assertIn("right:checkpoint_link_mismatch:1",self.check()["errors"])

    def test_previous_row_deleted(self):
        self.right["entries"][1]["rows"] = []
        self.assertFalse(self.check()["history_evidence_valid"])

    def test_consumed_row_reopened(self):
        row = self.right["entries"][1]["rows"][0]
        row["state"] = "ISSUED"
        row["consumed_at"] = None
        cp = self.right["entries"][1]["checkpoint"]
        cp["minimum_consumed"] = 0
        cp["rows_sha256"] = canonical_hash(self.right["entries"][1]["rows"])
        self.signed_second(self.right)
        self.pin_right = self.make_pin(self.right)
        self.assertFalse(self.check()["history_evidence_valid"])

    def test_changed_issued_timestamp(self):
        self.right["entries"][1]["rows"][0]["issued_at"] = 1
        self.assertFalse(self.check()["history_evidence_valid"])

    def test_forged_signature(self):
        self.right["entries"][1]["signature"]["signature_ed25519_hex"] = "0"*128
        self.assertFalse(self.check()["history_evidence_valid"])

    def test_new_signer_without_rotation(self):
        self.right["entries"][1]["independent_pin"]["key_id"] = "new-keeper"
        self.assertFalse(self.check()["history_evidence_valid"])

    def test_pinned_first_checkpoint_corrupt(self):
        self.pin_left["first_checkpoint_sha256"] = "0"*64
        self.assertIn("left:first_checkpoint_mismatch",self.check()["errors"])

    def test_epoch_head_rollback(self):
        self.head["minimum_last_sequence"] = 4
        self.assertIn("checkpoint_head_rollback",self.check()["errors"])

    def test_independently_valid_divergent_history(self):
        # At the next checkpoint, a distinct ISSUED challenge is legitimate
        # on one signed branch; two locally valid branches must still fail.
        second = self.right["entries"][1]
        second["rows"].append({
            "nonce_sha256": "f"*64, "challenge_sha256": "e"*64,
            "issued_at": 200, "expires_at": 250,
            "consumed_at": None, "state": "ISSUED",
        })
        second["checkpoint"]["row_count"] = 2
        second["checkpoint"]["rows_sha256"] = canonical_hash(second["rows"])
        second["independent_pin"]["minimum_rows"] = 1
        self.signed_second(self.right)
        self.pin_right = self.make_pin(self.right)
        v = self.check()
        self.assertIn("ledger_history_fork_detected",v["errors"])
        self.assertIn("right_external_head_mismatch",v["errors"])

    def test_history_anchor_tamper(self):
        self.pin_right["history_sha256"] = "f"*64
        self.assertIn("right:independent_history_anchor_mismatch", self.check()["errors"])

    def test_duplicate_nonce_in_later_snapshot(self):
        self.right["entries"][1]["rows"].append(
            copy.deepcopy(self.right["entries"][1]["rows"][0]))
        self.assertFalse(self.check()["history_evidence_valid"])

    def test_independent_head_mismatch(self):
        self.head["expected_history_sha256"] = "a"*64
        self.assertIn("left_external_head_mismatch",self.check()["errors"])

    def test_boolean_minimum_sequence(self):
        self.head["minimum_last_sequence"] = True
        self.assertIn("invalid_independent_head_pin", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
