"""GO-20 v28: signed security report, external anchor and rollback regression."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import ZERO, canonical_hash
from pr_final_report_attestation import (
    PIN_SCHEMA, STATEMENT_SCHEMA, TRUST_SCHEMA, assess_attestation,
)
from pr_security_acceptance import construct
from test_pr_governance_history import GovernanceHistoryTests


class MissingAttestationTests(unittest.TestCase):
    def test_missing_trust_denied(self):
        v = assess_attestation(None, None, None, None, None)
        self.assertIn("invalid_independent_attestation_trust", v["errors"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["release_authorized"])

    def test_missing_independent_pin_denied(self):
        v = assess_attestation(None, None, None,
                               {"schema": TRUST_SCHEMA, "keys": {"x": {}}}, None)
        self.assertIn("invalid_attestation_key_record", v["errors"])


class FinalAttestationTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("cryptography unavailable")
        base = GovernanceHistoryTests("test_valid_unchanged_history_still_denies")
        base.setUp()
        self.inputs = {
            "history": base.history,
            "independent_pin": base.pin,
            "controller_trust": base.trust,
        }
        self.report = construct(self.inputs)
        self.key = Ed25519PrivateKey.generate()
        pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.trust = {"schema": TRUST_SCHEMA, "keys": {
            "report-custodian": {
                "public_key_hex": pub, "status": "active",
                "role": "attestation_custodian",
            }
        }}
        self.previous = None
        self.pin = {"schema": PIN_SCHEMA, "expected_sequence": 0,
                    "previous_attestation_sha256": ZERO}
        self.envelope = self.sign(0, ZERO)

    def sign(self, sequence, previous):
        stmt = {
            "schema": STATEMENT_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "sequence": sequence,
            "previous_attestation_sha256": previous,
            "report_sha256": self.report["report_sha256"],
            "decision": "HOLD", "authorization": "DENY",
        }
        return {"statement": stmt, "signer_key_id": "report-custodian",
                "signature_ed25519_hex": self.key.sign(
                    bytes.fromhex(canonical_hash(stmt))).hex()}

    def advance(self):
        self.previous = self.envelope
        h = canonical_hash(self.previous)
        self.envelope = self.sign(1, h)
        self.pin = {"schema": PIN_SCHEMA, "expected_sequence": 1,
                    "previous_attestation_sha256": h}

    def verify(self):
        return assess_attestation(self.envelope, self.report, self.inputs,
                                  self.trust, self.pin, self.previous)

    def test_genesis_attested_review_stays_hold(self):
        v = self.verify()
        self.assertTrue(v["attestation_valid"], v["errors"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for name in ("release_authorized", "merge_authorized",
                     "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[name])

    def test_valid_anchored_second_attestation(self):
        self.advance()
        self.assertTrue(self.verify()["attestation_valid"], self.verify()["errors"])

    def test_sequence_rollback_detected(self):
        self.advance()
        self.envelope = self.sign(0, self.pin["previous_attestation_sha256"])
        self.assertIn("attestation_sequence_rollback_or_gap", self.verify()["errors"])

    def test_missing_predecessor_denied(self):
        self.advance()
        self.previous = None
        self.assertIn("missing_previous_attestation", self.verify()["errors"])

    def test_swapped_predecessor_denied(self):
        self.advance()
        self.previous = self.sign(0, ZERO)
        self.previous["signature_ed25519_hex"] = "0" * 128
        self.assertIn("independent_predecessor_pin_mismatch", self.verify()["errors"])

    def test_external_pin_tamper_denied(self):
        self.advance()
        self.pin["previous_attestation_sha256"] = "a" * 64
        self.assertIn("independent_predecessor_pin_mismatch", self.verify()["errors"])

    def test_missing_external_pin_denied(self):
        self.pin = None
        self.assertIn("invalid_independent_attestation_pin", self.verify()["errors"])

    def test_revoked_signer_denied(self):
        self.trust["keys"]["report-custodian"]["status"] = "revoked"
        self.assertIn("untrusted_revoked_or_wrong_role_signer", self.verify()["errors"])

    def test_wrong_signer_role_denied(self):
        self.trust["keys"]["report-custodian"]["role"] = "security_reviewer"
        self.assertFalse(self.verify()["attestation_valid"])

    def test_modified_signature_denied(self):
        self.envelope["signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(x.startswith("attestation_signature:") for x in self.verify()["errors"]))

    def test_changed_security_report_denied(self):
        self.report["authorization"] = "ALLOW"
        self.assertTrue(any(x.startswith("report:") for x in self.verify()["errors"]))

    def test_changed_independent_governance_anchor_denied(self):
        self.inputs["independent_pin"]["last_policy_sha256"] = ZERO
        self.assertTrue(any(x.startswith("report:") for x in self.verify()["errors"]))

    def test_forged_release_statement_denied(self):
        self.envelope["statement"]["authorization"] = "ALLOW"
        self.assertIn("unauthorized_attestation_statement", self.verify()["errors"])

    def test_separation_from_governance_controller_key(self):
        self.trust["keys"]["report-custodian"]["public_key_hex"] = (
            self.inputs["controller_trust"]["controllers"]["governance-controller"]["public_key_hex"])
        self.assertIn("attestation_key_role_overlap", self.verify()["errors"])

    def test_genesis_predecessor_not_allowed(self):
        self.previous = copy.deepcopy(self.envelope)
        self.assertIn("unexpected_genesis_predecessor", self.verify()["errors"])

    def test_reused_nonzero_genesis_anchor_rejected(self):
        self.pin["previous_attestation_sha256"] = "a" * 64
        self.assertIn("invalid_independent_attestation_pin_fields", self.verify()["errors"])


if __name__ == "__main__":
    unittest.main()
