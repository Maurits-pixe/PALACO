"""GO-20 v54: witnessed key rotation, historical revocations and rollback."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_custodian_rotation_witnesses import (
    SCHEMA, TRUST_SCHEMA, REVOKE_SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, assess
)
from test_pr_ledger_receipt_succession import SuccessionTests


class InvalidWitnessTests(unittest.TestCase):
    def test_missing_evidence_denied(self):
        r = assess(*([None] * 9))
        self.assertFalse(r["rotation_evidence_valid"])
        self.assertEqual((r["decision"], r["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(r["trust_registry_promoted"])


class RotationWitnessTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        base = SuccessionTests("test_two_matching_view_histories_still_deny")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        self.private = {k: Ed25519PrivateKey.generate()
                        for k in ("observer-a", "observer-b", "observer-c")}
        self.trust = {"schema": TRUST_SCHEMA, "witnesses": {}}
        for mid, secret in self.private.items():
            self.trust["witnesses"][mid] = {
                "public_key_hex": secret.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "organization_id": "org-" + mid, "domain_id": "domain-" + mid,
                "status": "active",
            }
        self.revocations = {"schema": REVOKE_SCHEMA, "entries": []}
        self.pin = {
            "schema": PIN_SCHEMA,
            "view_sha256": canonical_hash(base.left),
            "witness_trust_sha256": canonical_hash(self.trust),
            "revocations_sha256": canonical_hash(self.revocations),
            "minimum_round": 11, "quorum": 2,
        }
        self.testimony = {"schema": SCHEMA, "transitions": []}
        self.make_transition()

    def make_transition(self):
        old, new = self.base.left["rounds"]
        expected = {
            "round": new["round"],
            "old_trust_sha256": canonical_hash(old["sources"]["trust"]),
            "new_trust_sha256": canonical_hash(new["sources"]["trust"]),
            "rotations_sha256": canonical_hash([]),
        }
        record = {**expected, "signatures": []}
        self.testimony["transitions"] = [record]
        self.sign(record)

    def sign(self, record):
        record["signatures"] = []
        for mid in ("observer-a", "observer-b"):
            expected = {k: record[k] for k in (
                "round", "old_trust_sha256", "new_trust_sha256", "rotations_sha256")}
            statement = {
                "schema": STATEMENT_SCHEMA, **expected,
                "view_sha256": self.pin["view_sha256"],
                "revocations_sha256": self.pin["revocations_sha256"],
                "witness_trust_sha256": self.pin["witness_trust_sha256"],
                "witness_id": mid,
                "decision": "HOLD", "authorization": "DENY",
            }
            signature = self.private[mid].sign(
                bytes.fromhex(canonical_hash(statement))).hex()
            record["signatures"].append({
                "witness_id": mid, "signature_ed25519_hex": signature,
            })

    def check(self):
        b = self.base
        return assess(b.left, b.left_pin, b.right, b.right_pin, b.head,
                      self.testimony, self.trust, self.revocations, self.pin)

    def test_two_independent_signatures_still_hold(self):
        v = self.check()
        self.assertTrue(v["rotation_evidence_valid"], v["errors"])
        self.assertEqual((v["transitions_verified"], v["witness_signatures_verified"]), (1, 2))
        for key in ("trust_registry_promoted", "revocation_enforced_in_production",
                    "history_restored", "archive_published", "failover_authorized",
                    "merge_authorized", "deployment_authorized",
                    "production_commit_performed"):
            self.assertFalse(v[key])

    def test_missing_witness_signature(self):
        self.testimony["transitions"][0]["signatures"].pop()
        self.assertFalse(self.check()["rotation_evidence_valid"])

    def test_forged_signature(self):
        self.testimony["transitions"][0]["signatures"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertIn("invalid_witness_signature:0:observer-a", self.check()["errors"])

    def test_duplicate_signer(self):
        a = self.testimony["transitions"][0]["signatures"]
        a[1] = copy.deepcopy(a[0])
        self.assertIn("duplicate_or_unknown_witness:0:1", self.check()["errors"])

    def test_wrong_witness_key(self):
        self.trust["witnesses"]["observer-a"]["public_key_hex"] = "f" * 64
        self.assertIn("independent_anchor_mismatch", self.check()["errors"])

    def test_wrong_signer_domain(self):
        self.trust["witnesses"]["observer-b"]["domain_id"] = "domain-observer-a"
        self.pin["witness_trust_sha256"] = canonical_hash(self.trust)
        self.sign(self.testimony["transitions"][0])
        self.assertIn("witness_custody_overlap:0:observer-b", self.check()["errors"])

    def test_revoked_witness(self):
        self.trust["witnesses"]["observer-b"]["status"] = "revoked"
        self.pin["witness_trust_sha256"] = canonical_hash(self.trust)
        self.sign(self.testimony["transitions"][0])
        self.assertIn("invalid_witness:0:observer-b", self.check()["errors"])

    def test_revocation_registry_changed_without_external_pin(self):
        self.revocations["entries"].append({
            "custodian_id": "archive-a",
            "public_key_hex": "f" * 64,
            "effective_round": 11,
        })
        self.assertIn("independent_anchor_mismatch", self.check()["errors"])

    def test_revoked_active_key_detected_even_with_valid_signatures(self):
        public = self.base.left["rounds"][1]["sources"]["trust"]["custodians"]["archive-a"]["public_key_hex"]
        self.revocations["entries"].append({
            "custodian_id": "archive-a",
            "public_key_hex": public,
            "effective_round": 11,
        })
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.sign(self.testimony["transitions"][0])
        self.assertIn("revoked_key_reactivated:0:archive-a", self.check()["errors"])

    def test_duplicate_revocation(self):
        record = {"custodian_id": "archive-a", "public_key_hex": "a" * 64, "effective_round": 11}
        self.revocations["entries"] = [record, copy.deepcopy(record)]
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.sign(self.testimony["transitions"][0])
        self.assertIn("duplicate_revocation:1", self.check()["errors"])

    def test_malformed_revocation_round(self):
        self.revocations["entries"].append({
            "custodian_id": "archive-a", "public_key_hex": "a" * 64,
            "effective_round": True,
        })
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.sign(self.testimony["transitions"][0])
        self.assertIn("invalid_revocation:0", self.check()["errors"])

    def test_transition_registry_forged(self):
        self.testimony["transitions"][0]["new_trust_sha256"] = "0" * 64
        self.assertIn("transition_binding_mismatch:0", self.check()["errors"])

    def test_replay_signature_under_different_minimum_round(self):
        self.pin["minimum_round"] = 12
        self.assertIn("round_rollback", self.check()["errors"])

    def test_rollback_view_anchor_detected(self):
        self.pin["view_sha256"] = "a" * 64
        self.assertIn("independent_anchor_mismatch", self.check()["errors"])

    def test_missing_original_receipt_round_denied(self):
        self.base.right["rounds"].pop()
        self.assertTrue(any(e.startswith("v53:") for e in self.check()["errors"]))

    def test_boolean_quorum_denied(self):
        self.pin["quorum"] = True
        self.assertIn("invalid_independent_witness_pin", self.check()["errors"])

    def test_wrong_witness_identifier(self):
        self.testimony["transitions"][0]["signatures"][1]["witness_id"] = "intruder"
        self.assertFalse(self.check()["rotation_evidence_valid"])

    def test_stronger_quorum_refuses_two_signatures(self):
        self.pin["quorum"] = 3
        self.assertIn("insufficient_rotation_witness_quorum:0", self.check()["errors"])

    def test_no_independent_view_cannot_be_repaired(self):
        self.base.head["view_sha256"] = "0" * 64
        self.assertFalse(self.check()["rotation_evidence_valid"])


if __name__ == "__main__":
    unittest.main()
