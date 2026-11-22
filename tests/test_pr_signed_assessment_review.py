"""GO-20 v23 signed receipt review: role separation and release-denial tests."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_assessment_receipt import construct_receipt
from pr_signed_assessment_review import (
    SCHEMA, STATEMENT_SCHEMA, TRUST_SCHEMA, verify_review,
)
from test_pr_multiround_assessor import MultiRoundTests


class InvalidReviews(unittest.TestCase):
    def test_missing_review(self):
        v = verify_review(None, None, None, None)
        self.assertIn("invalid_review_envelope", v["errors"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["release_authorized"])

    def test_missing_trust(self):
        envelope = {"schema": SCHEMA, "receipt_sha256": "0" * 64,
                    "attestations": [{}, {}]}
        v = verify_review(envelope, None, None, None)
        self.assertIn("invalid_reviewer_trust", v["errors"])


class SignedReviews(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("optional cryptography backend unavailable")
        base = MultiRoundTests("test_three_rounds_valid_but_no_authority")
        base.setUp()
        self.inputs = {
            "roundbook": base.roundbook, "audit_trust": base.audit_trust,
            "witness_trust": base.witness_trust, "logbook": base.logbook,
            "external_pins": base.pins, "baseline": base.baseline,
        }
        self.receipt = construct_receipt(self.inputs)
        self.keys = {"evidence": Ed25519PrivateKey.generate(),
                     "security": Ed25519PrivateKey.generate()}
        roles = {"evidence": "evidence_reviewer", "security": "security_reviewer"}
        self.trust = {"schema": TRUST_SCHEMA, "reviewers": {
            name: {
                "public_key_hex": key.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "status": "active", "role": roles[name],
            }
            for name, key in self.keys.items()
        }}
        self.envelope = {"schema": SCHEMA,
                         "receipt_sha256": self.receipt["receipt_sha256"],
                         "attestations": [self.attest(n, roles[n])
                                          for n in ("evidence", "security")]}

    def attest(self, reviewer, role):
        statement = {"schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
                     "receipt_sha256": self.receipt["receipt_sha256"],
                     "role": role, "reviewer_id": reviewer,
                     "decision": "HOLD", "authorization": "DENY"}
        return {"role": role, "reviewer_id": reviewer,
                "signature_ed25519_hex": self.keys[reviewer].sign(
                    bytes.fromhex(canonical_hash(statement))).hex()}

    def check(self):
        return verify_review(self.envelope, self.receipt, self.inputs, self.trust)

    def test_valid_independent_review_stays_hold_deny(self):
        v = self.check()
        self.assertTrue(v["review_valid"], v["errors"])
        self.assertEqual(v["reviewer_roles_verified"], 2)
        self.assertFalse(v["release_authorized"])
        self.assertFalse(v["production_commit_performed"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_revoked_security_reviewer(self):
        self.trust["reviewers"]["security"]["status"] = "revoked"
        self.assertIn("untrusted_revoked_or_wrong_role:1", self.check()["errors"])

    def test_wrong_role_reviewer(self):
        self.trust["reviewers"]["security"]["role"] = "evidence_reviewer"
        self.assertIn("untrusted_revoked_or_wrong_role:1", self.check()["errors"])

    def test_untrusted_reviewer(self):
        self.envelope["attestations"][1]["reviewer_id"] = "unknown"
        self.assertIn("untrusted_revoked_or_wrong_role:1", self.check()["errors"])

    def test_duplicate_role(self):
        self.envelope["attestations"][1]["role"] = "evidence_reviewer"
        self.assertIn("invalid_or_duplicate_role:1", self.check()["errors"])

    def test_same_reviewer_both_roles(self):
        self.envelope["attestations"][1]["reviewer_id"] = "evidence"
        self.assertIn("reviewer_separation_failed:1", self.check()["errors"])

    def test_modified_signature(self):
        self.envelope["attestations"][1]["signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(e.startswith("signature:1:") for e in self.check()["errors"]))

    def test_modified_receipt(self):
        self.receipt["assessment"]["authorization"] = "ALLOW"
        self.assertTrue(any(e.startswith("receipt:") for e in self.check()["errors"]))

    def test_changed_input(self):
        self.inputs["baseline"]["last_payload_sha256"] = "0" * 64
        self.assertIn("receipt:technical_assessment_failed", self.check()["errors"])

    def test_wrong_receipt_binding(self):
        self.envelope["receipt_sha256"] = "0" * 64
        self.assertIn("receipt_binding_mismatch", self.check()["errors"])

    def test_missing_second_attestation(self):
        self.envelope["attestations"].pop()
        self.assertIn("invalid_review_envelope", self.check()["errors"])

    def test_same_public_key_across_distinct_reviewers_rejected(self):
        self.trust["reviewers"]["security"]["public_key_hex"] = self.trust["reviewers"]["evidence"]["public_key_hex"]
        self.assertIn("reviewer_public_key_reuse:1", self.check()["errors"])

    def test_forged_public_key(self):
        self.trust["reviewers"]["security"]["public_key_hex"] = "a" * 64
        self.assertFalse(self.check()["review_valid"])


if __name__ == "__main__":
    unittest.main()
