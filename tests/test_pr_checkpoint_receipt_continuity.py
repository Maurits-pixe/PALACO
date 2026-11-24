"""GO-20 v46: signed checkpoint succession, missing publication and rollback."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_checkpoint_receipt_continuity import (
    SCHEMA, PIN_SCHEMA, RECEIPT_SCHEMA, ZERO, verify_continuity,
)
from test_pr_transparency_checkpoint_views import CheckpointTests


class InvalidContinuityTests(unittest.TestCase):
    def test_missing_evidence_fails_closed(self):
        v = verify_continuity(None, None, None, None)
        self.assertFalse(v["publication_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["checkpoint_published"])

    def test_invalid_pin_fails_closed(self):
        self.assertIn("invalid_checkpoint_chain",
                      verify_continuity({}, {}, {}, {})["errors"])


class ReceiptContinuityTests(unittest.TestCase):
    def setUp(self):
        base = CheckpointTests("test_valid_two_views_still_deny_authority")
        base.setUp()
        self.base = base
        b = base.base
        self.v45 = {
            "left_history": b.left, "left_pin": b.left_pin,
            "right_history": b.right, "right_pin": b.right_pin,
            "revocations": b.revocations, "signed_register": b.signed,
            "v44_pin": b.pin, "views": base.views,
            "trust": base.trust, "independent_pin": base.pin,
        }
        self.trust = base.trust
        initial = copy.deepcopy(base.checkpoint)
        initial["sequence"] = 43
        self.chain = {"schema": SCHEMA, "entries": [
            {"sequence": 43, "previous_entry_sha256": ZERO,
             "checkpoint": initial, "receipts": []},
            {"sequence": 44, "previous_entry_sha256": ZERO,
             "checkpoint": copy.deepcopy(base.checkpoint), "receipts": []},
        ]}
        self.sign_entry(0)
        self.chain["entries"][1]["previous_entry_sha256"] = canonical_hash(
            self.chain["entries"][0])
        self.sign_entry(1)
        self.pin = {
            "schema": PIN_SCHEMA, "first_sequence": 43, "last_sequence": 44,
            "first_entry_sha256": canonical_hash(self.chain["entries"][0]),
            "last_entry_sha256": canonical_hash(self.chain["entries"][1]),
            "trust_sha256": canonical_hash(self.trust), "quorum": 2,
        }

    def sign_entry(self, index):
        entry = self.chain["entries"][index]
        entry["receipts"] = []
        for witness_id in ("keeper-a", "keeper-b"):
            statement = {
                "schema": RECEIPT_SCHEMA, "repository": "Maurits-pixe/PALACO",
                "sequence": entry["sequence"],
                "checkpoint_sha256": canonical_hash(entry["checkpoint"]),
                "previous_entry_sha256": entry["previous_entry_sha256"],
                "trust_sha256": canonical_hash(self.trust),
                "witness_id": witness_id,
                "decision": "HOLD", "authorization": "DENY",
            }
            sig = self.base.private[witness_id].sign(
                bytes.fromhex(canonical_hash(statement))).hex()
            entry["receipts"].append({
                "witness_id": witness_id, "signature_ed25519_hex": sig,
            })

    def repin(self):
        self.pin["first_entry_sha256"] = canonical_hash(self.chain["entries"][0])
        self.pin["last_entry_sha256"] = canonical_hash(self.chain["entries"][-1])

    def check(self):
        return verify_continuity(self.chain, self.pin, self.trust, self.v45)

    def test_complete_chain_remains_hold(self):
        v = self.check()
        self.assertTrue(v["publication_evidence_valid"], v["errors"])
        self.assertEqual(v["checkpoints_verified"], 2)
        self.assertEqual(v["receipts_verified"], 4)
        for field in ("checkpoint_published", "remote_publication_verified",
                      "failover_authorized", "promotion_performed",
                      "merge_authorized", "production_commit_performed"):
            self.assertFalse(v[field])

    def test_missing_latest_entry(self):
        self.chain["entries"].pop()
        self.assertIn("invalid_checkpoint_chain", self.check()["errors"])

    def test_sequence_gap(self):
        self.chain["entries"][1]["sequence"] = 45
        self.assertIn("invalid_or_missing_checkpoint:1", self.check()["errors"])

    def test_swapped_checkpoints(self):
        self.chain["entries"].reverse()
        self.assertFalse(self.check()["publication_evidence_valid"])

    def test_hash_link_replaced(self):
        self.chain["entries"][1]["previous_entry_sha256"] = "a" * 64
        self.sign_entry(1)
        self.repin()
        self.assertIn("checkpoint_chain_link_mismatch:1", self.check()["errors"])

    def test_missing_receipt(self):
        self.chain["entries"][0]["receipts"].pop()
        self.assertIn("invalid_or_missing_checkpoint:0", self.check()["errors"])

    def test_forged_receipt(self):
        self.chain["entries"][1]["receipts"][0]["signature_ed25519_hex"] = "0" * 128
        self.repin()
        self.assertFalse(self.check()["publication_evidence_valid"])

    def test_duplicate_receipt(self):
        e = self.chain["entries"][1]
        e["receipts"][1] = copy.deepcopy(e["receipts"][0])
        self.repin()
        self.assertIn("duplicate_or_unknown_receipt:1:1", self.check()["errors"])

    def test_revoked_signer(self):
        self.trust["witnesses"]["keeper-b"]["status"] = "revoked"
        self.assertFalse(self.check()["publication_evidence_valid"])

    def test_trust_anchor_replaced(self):
        self.pin["trust_sha256"] = "a" * 64
        self.assertIn("receipt_trust_anchor_mismatch", self.check()["errors"])

    def test_first_entry_tampered(self):
        self.chain["entries"][0]["checkpoint"]["history_sha256"] = "f" * 64
        self.assertIn("first_checkpoint_anchor_mismatch", self.check()["errors"])

    def test_last_entry_tampered(self):
        self.chain["entries"][1]["checkpoint"]["history_sha256"] = "f" * 64
        self.assertIn("last_checkpoint_anchor_mismatch", self.check()["errors"])

    def test_wrong_final_head_even_with_repin_and_resign(self):
        self.chain["entries"][1]["checkpoint"]["history_sha256"] = "f" * 64
        self.sign_entry(1)
        self.repin()
        self.assertIn("final_checkpoint_does_not_match_v45", self.check()["errors"])

    def test_minimum_quorum_raised(self):
        self.pin["quorum"] = 3
        self.assertIn("missing_publication_receipts:0", self.check()["errors"])

    def test_boolean_quorum_rejected(self):
        self.pin["quorum"] = True
        self.assertIn("invalid_independent_continuity_pin", self.check()["errors"])

    def test_external_epoch_pin_rollback(self):
        self.pin["first_sequence"] = 42
        self.assertFalse(self.check()["publication_evidence_valid"])

    def test_underlying_v45_fork_denied(self):
        self.base.base.fork_with_valid_alternative_votes()
        self.assertTrue(any(x.startswith("v45:") for x in self.check()["errors"]))

    def test_repeat_receipt_from_other_checkpoint_fails(self):
        self.chain["entries"][1]["receipts"] = copy.deepcopy(
            self.chain["entries"][0]["receipts"])
        self.repin()
        self.assertFalse(self.check()["publication_evidence_valid"])

    def test_wrong_control_domain(self):
        self.trust["witnesses"]["keeper-b"]["domain_id"] = "domain-keeper-a"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.assertFalse(self.check()["publication_evidence_valid"])

    def test_nonmatching_v45_latest_head(self):
        self.chain["entries"][1]["checkpoint"]["sequence"] = 45
        self.sign_entry(1)
        self.repin()
        self.assertIn("invalid_checkpoint_content:1", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
