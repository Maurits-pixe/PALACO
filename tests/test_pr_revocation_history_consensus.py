"""GO-20 v55: signed revocation history and conflicting observer regressions."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_revocation_history_consensus import (
    SCHEMA, VIEW_SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, ZERO, assess
)
from test_pr_custodian_rotation_witnesses import RotationWitnessTests


class InvalidRevocationHistoryTests(unittest.TestCase):
    def test_absent_data_denied(self):
        v = assess(*([None] * 6))
        self.assertFalse(v["revocation_history_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))


class RevocationHistoryTests(unittest.TestCase):
    def setUp(self):
        source = RotationWitnessTests("test_two_independent_signatures_still_hold")
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.source = source
        b = source.base
        self.v54 = {
            "left": b.left, "left_pin": b.left_pin,
            "right": b.right, "right_pin": b.right_pin,
            "head": b.head, "testimony": source.testimony,
            "witness_trust": source.trust,
            "revocations": source.revocations,
            "independent_pin": source.pin,
        }
        self.external = {
            "schema": "palaco.go20-revocation-history-independent-head.v1",
            "trust_sha256": canonical_hash(source.trust),
            "final_revocations_sha256": canonical_hash(source.revocations),
            "expected_view_sha256": "0" * 64,
            "minimum_last_epoch": 21, "quorum": 2,
        }
        first = {"epoch": 20, "previous_sha256": ZERO,
                 "revocations": copy.deepcopy(source.revocations), "signatures": []}
        self.sign(first)
        second = {"epoch": 21, "previous_sha256": canonical_hash(first),
                  "revocations": copy.deepcopy(source.revocations), "signatures": []}
        self.sign(second)
        self.left = {"schema": VIEW_SCHEMA, "epochs": [first, second]}
        self.right = copy.deepcopy(self.left)
        self.left_pin = self.repin(self.left)
        self.right_pin = self.repin(self.right)
        self.external["expected_view_sha256"] = canonical_hash(self.left)

    def sign(self, entry):
        entry["signatures"] = []
        for wid in ("observer-a", "observer-b"):
            statement = {
                "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
                "epoch": entry["epoch"], "previous_sha256": entry["previous_sha256"],
                "revocations_sha256": canonical_hash(entry["revocations"]),
                "witness_trust_sha256": self.external["trust_sha256"],
                "final_revocations_sha256": self.external["final_revocations_sha256"],
                "witness_id": wid, "decision": "HOLD", "authorization": "DENY",
            }
            signature = self.source.private[wid].sign(
                bytes.fromhex(canonical_hash(statement))).hex()
            entry["signatures"].append({"witness_id": wid,
                                         "signature_ed25519_hex": signature})

    def repin(self, view):
        return {"schema": PIN_SCHEMA, "first_epoch": 20, "last_epoch": 21,
                "view_sha256": canonical_hash(view),
                "final_revocations_sha256": canonical_hash(view["epochs"][-1]["revocations"])}

    def check(self):
        return assess(self.left, self.left_pin, self.right, self.right_pin,
                      self.external, self.v54)

    def test_two_observers_valid_still_deny(self):
        v = self.check()
        self.assertTrue(v["revocation_history_valid"], v["errors"])
        self.assertEqual((v["epochs_verified"], v["signatures_verified"]), (4, 8))
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["revocation_enforced_in_production"])
        self.assertFalse(v["trust_registry_promoted"])
        self.assertFalse(v["production_commit_performed"])

    def test_missing_epoch_denied(self):
        self.right["epochs"].pop()
        self.assertFalse(self.check()["revocation_history_valid"])

    def test_epoch_skip_denied(self):
        self.right["epochs"][1]["epoch"] = 23
        self.assertIn("right:invalid_epoch:1", self.check()["errors"])

    def test_link_rewritten_after_resigning_denied(self):
        self.right["epochs"][1]["previous_sha256"] = "a" * 64
        self.sign(self.right["epochs"][1])
        self.right_pin = self.repin(self.right)
        self.assertIn("right:broken_epoch_link:1", self.check()["errors"])

    def test_forged_witness_signature(self):
        self.right["epochs"][0]["signatures"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertIn("right:invalid_witness_signature:0:observer-a", self.check()["errors"])

    def test_duplicate_witness(self):
        self.right["epochs"][0]["signatures"][1] = copy.deepcopy(
            self.right["epochs"][0]["signatures"][0])
        self.assertIn("right:duplicate_or_unknown_witness:0:1", self.check()["errors"])

    def test_quorum_raise_denies(self):
        self.external["quorum"] = 3
        self.assertIn("left:insufficient_witness_quorum:0", self.check()["errors"])

    def test_nonce_status_changed_denied_by_v54(self):
        self.v54["right"]["rounds"].pop()
        self.assertTrue(any(e.startswith("v54:") for e in self.check()["errors"]))

    def test_revocations_changed_without_pin(self):
        self.external["final_revocations_sha256"] = "f" * 64
        self.assertIn("external_revocation_or_trust_anchor_mismatch", self.check()["errors"])

    def test_witness_key_substitution(self):
        self.source.trust["witnesses"]["observer-a"]["public_key_hex"] = "f" * 64
        self.assertIn("external_revocation_or_trust_anchor_mismatch", self.check()["errors"])

    def test_boolean_quorum_denied(self):
        self.external["quorum"] = True
        self.assertIn("invalid_independent_head", self.check()["errors"])

    def test_stale_epoch_rejected(self):
        self.external["minimum_last_epoch"] = 22
        self.assertIn("history_epoch_rollback", self.check()["errors"])

    def test_wrong_observer_head(self):
        self.external["expected_view_sha256"] = "a" * 64
        self.assertIn("left_external_head_mismatch", self.check()["errors"])

    def test_view_pin_tampering(self):
        self.right_pin["view_sha256"] = "f" * 64
        self.assertIn("right:observer_view_anchor_mismatch", self.check()["errors"])

    def test_changed_witness_domain(self):
        self.source.trust["witnesses"]["observer-b"]["domain_id"] = "domain-observer-a"
        self.external["trust_sha256"] = canonical_hash(self.source.trust)
        self.v54["independent_pin"]["witness_trust_sha256"] = canonical_hash(self.source.trust)
        self.source.pin["witness_trust_sha256"] = canonical_hash(self.source.trust)
        self.source.sign(self.source.testimony["transitions"][0])
        self.assertFalse(self.check()["revocation_history_valid"])

    def test_removed_revocation_detection(self):
        # Early snapshot has a revoked historical key, then loses it.
        item = {"custodian_id": "archive-a", "public_key_hex": "f" * 64,
                "effective_round": 21}
        first = self.right["epochs"][0]
        first["revocations"]["entries"].append(item)
        self.sign(first)
        second = self.right["epochs"][1]
        second["previous_sha256"] = canonical_hash(first)
        self.sign(second)
        self.right_pin = self.repin(self.right)
        self.assertIn("right:revocation_removed_or_rewritten:1", self.check()["errors"])

    def test_conflicting_validly_signed_observer_histories(self):
        # One view includes an extra historical (not active) revocation
        # during the first epoch, then retains it in final epoch. v54's
        # pinned final revocations must reject this divergence.
        item = {"custodian_id": "inactive-custodian",
                "public_key_hex": "f" * 64, "effective_round": 20}
        self.right["epochs"][0]["revocations"]["entries"].append(item)
        self.sign(self.right["epochs"][0])
        self.right["epochs"][1]["previous_sha256"] = canonical_hash(self.right["epochs"][0])
        self.right["epochs"][1]["revocations"]["entries"].append(item)
        self.sign(self.right["epochs"][1])
        self.right_pin = self.repin(self.right)
        self.assertFalse(self.check()["revocation_history_valid"])

    def test_duplicate_revocation_rejected(self):
        item = {"custodian_id": "inactive", "public_key_hex": "f" * 64,
                "effective_round": 20}
        self.right["epochs"][1]["revocations"]["entries"] = [item, copy.deepcopy(item)]
        self.assertIn("right:invalid_revocations:1:duplicate_revocation", self.check()["errors"])

    def test_unknown_witness_denied(self):
        self.right["epochs"][0]["signatures"][0]["witness_id"] = "intruder"
        self.assertFalse(self.check()["revocation_history_valid"])


if __name__ == "__main__":
    unittest.main()
