"""GO-20 v53: offline receipt succession, forks and signer-rotation failures."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_ledger_receipt_succession import SCHEMA, PIN_SCHEMA, ZERO, assess
from test_pr_ledger_history_receipts import LedgerReceiptTests


class MissingSuccessionTests(unittest.TestCase):
    def test_null_evidence_is_hold_deny(self):
        v = assess(None, None, None, None, None)
        self.assertFalse(v["succession_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["history_restored"])


class SuccessionTests(unittest.TestCase):
    def setUp(self):
        original = LedgerReceiptTests("test_verified_receipts_still_hold_deny")
        original.setUp()
        self.addCleanup(original.doCleanups)
        self.original = original
        b = original.base
        sources = {
            "left": b.left, "left_pin": b.pin_left,
            "right": b.right, "right_pin": b.pin_right,
            "head": b.head, "archive": original.archive,
            "trust": original.trust, "external_pin": original.pin,
        }
        one = {"round": 10, "previous_round_sha256": ZERO, "sources": copy.deepcopy(sources)}
        two = {"round": 11, "previous_round_sha256": canonical_hash(one),
               "sources": copy.deepcopy(sources)}
        self.left = {"schema": SCHEMA, "rounds": [one, two], "rotations": []}
        self.right = copy.deepcopy(self.left)
        self.left_pin = self.repin(self.left)
        self.right_pin = self.repin(self.right)
        self.head = {
            "schema": "palaco.go20-ledger-receipt-head-pin.v1",
            "view_sha256": canonical_hash(self.left),
            "minimum_round": 11,
        }

    def repin(self, view):
        return {
            "schema": PIN_SCHEMA,
            "first_round": 10, "last_round": 11,
            "first_round_sha256": canonical_hash(view["rounds"][0]),
            "last_round_sha256": canonical_hash(view["rounds"][-1]),
            "view_sha256": canonical_hash(view),
            "minimum_receipts": 2,
            "minimum_ledger_sequence": 3,
        }

    def check(self):
        return assess(self.left, self.left_pin, self.right, self.right_pin, self.head)

    def test_two_matching_view_histories_still_deny(self):
        v = self.check()
        self.assertTrue(v["succession_evidence_valid"], v["errors"])
        self.assertEqual(v["rounds_verified"], 4)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for key in ("history_restored", "archive_published", "trust_registry_promoted",
                    "challenge_reopened", "failover_authorized", "merge_authorized",
                    "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[key])

    def test_missing_receipt_round(self):
        self.right["rounds"].pop()
        self.assertFalse(self.check()["succession_evidence_valid"])

    def test_skipped_round(self):
        self.right["rounds"][1]["round"] += 1
        self.assertIn("right:invalid_or_missing_round:1", self.check()["errors"])

    def test_broken_link_with_repin(self):
        self.right["rounds"][1]["previous_round_sha256"] = "a" * 64
        self.right_pin = self.repin(self.right)
        self.assertIn("right:broken_round_link:1", self.check()["errors"])

    def test_rewritten_history_blocked(self):
        self.right["rounds"][1]["sources"]["left"]["entries"].pop()
        self.assertFalse(self.check()["succession_evidence_valid"])

    def test_forged_receipt_blocked(self):
        self.right["rounds"][1]["sources"]["archive"]["receipts"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertFalse(self.check()["succession_evidence_valid"])

    def test_independent_view_pin_substitution(self):
        self.right_pin["view_sha256"] = "a" * 64
        self.assertIn("right:independent_view_anchor_mismatch", self.check()["errors"])

    def test_first_round_anchor_mismatch(self):
        self.left_pin["first_round_sha256"] = "f" * 64
        self.assertIn("left:first_round_anchor_mismatch", self.check()["errors"])

    def test_last_round_anchor_mismatch(self):
        self.left_pin["last_round_sha256"] = "f" * 64
        self.assertIn("left:last_round_anchor_mismatch", self.check()["errors"])

    def test_ledger_floor_rollback(self):
        self.right_pin["minimum_ledger_sequence"] = 4
        self.assertIn("right:round_retention_floor_downgrade:0", self.check()["errors"])

    def test_minimum_receipts_rollback(self):
        self.right_pin["minimum_receipts"] = 3
        self.assertIn("right:round_retention_floor_downgrade:0", self.check()["errors"])

    def test_unexpected_key_substitution(self):
        self.right["rounds"][1]["sources"]["trust"]["custodians"]["archive-a"]["public_key_hex"] = "a" * 64
        self.assertFalse(self.check()["succession_evidence_valid"])

    def test_forged_unnecessary_rotation(self):
        self.right["rotations"].append({"round": 11, "custodian_id": "archive-a",
            "old_public_key_hex": "a"*64, "new_public_key_hex": "b"*64,
            "old_trust_sha256": "c"*64, "new_trust_sha256": "d"*64,
            "old_signature_ed25519_hex": "0"*128, "new_signature_ed25519_hex": "0"*128})
        self.right_pin = self.repin(self.right)
        self.assertIn("right:unnecessary_rotation:1:archive-a", self.check()["errors"])

    def test_orphan_rotation(self):
        self.right["rotations"].append({"round": 99, "custodian_id": "archive-a",
            "old_public_key_hex": "a"*64, "new_public_key_hex": "b"*64,
            "old_trust_sha256": "c"*64, "new_trust_sha256": "d"*64,
            "old_signature_ed25519_hex": "0"*128, "new_signature_ed25519_hex": "0"*128})
        self.right_pin = self.repin(self.right)
        self.assertIn("right:orphan_rotation", self.check()["errors"])

    def test_duplicate_rotation_record(self):
        record = {"round": 99, "custodian_id": "archive-a",
            "old_public_key_hex": "a"*64, "new_public_key_hex": "b"*64,
            "old_trust_sha256": "c"*64, "new_trust_sha256": "d"*64,
            "old_signature_ed25519_hex": "0"*128, "new_signature_ed25519_hex": "0"*128}
        self.right["rotations"] = [record, copy.deepcopy(record)]
        self.right_pin = self.repin(self.right)
        self.assertIn("right:duplicate_rotation:1", self.check()["errors"])

    def test_boolean_minimum_round_rejected(self):
        self.head["minimum_round"] = True
        self.assertIn("invalid_independent_head", self.check()["errors"])

    def test_external_head_mismatch(self):
        self.head["view_sha256"] = "0"*64
        self.assertIn("left_external_head_mismatch", self.check()["errors"])

    def test_round_rollback_detected(self):
        self.head["minimum_round"] = 12
        self.assertIn("receipt_head_rollback", self.check()["errors"])

    def test_contradictory_signed_receipt_registers(self):
        # Same complete, valid history with different receipt order;
        # both pass v52, but a conflicting independent view is denied.
        r = self.right["rounds"][1]
        r["sources"]["archive"]["receipts"].reverse()
        r["sources"]["external_pin"]["minimum_receipts"] = 2
        self.right["rounds"][0]["sources"]["archive"]["receipts"].reverse()
        self.right["rounds"][1]["previous_round_sha256"] = canonical_hash(self.right["rounds"][0])
        self.right_pin = self.repin(self.right)
        v = self.check()
        self.assertIn("contradictory_receipt_registers", v["errors"])
        self.assertIn("right_external_head_mismatch", v["errors"])


if __name__ == "__main__":
    unittest.main()
