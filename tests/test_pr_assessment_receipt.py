"""GO-20 v22: negative receipt tampering, coverage and recomputation checks."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_assessment_receipt import (
    EVIDENCE_KEYS, construct_receipt, safe_assess, verify_receipt, unique_pairs,
)
from test_pr_multiround_assessor import MultiRoundTests


class MalformedReceiptTests(unittest.TestCase):
    def test_missing_inputs_fail_closed(self):
        report = safe_assess(None)
        self.assertFalse(report["technical_evidence_valid"])
        self.assertEqual((report["decision"], report["authorization"]), ("HOLD", "DENY"))

    def test_missing_component_fail_closed(self):
        self.assertIn("invalid_independent_inputs", verify_receipt({}, {})["errors"])

    def test_wrong_schema_rejected(self):
        self.assertIn("invalid_receipt_schema", verify_receipt({"schema": "wrong"}, {})["errors"])

    def test_malformed_nested_evidence_denied(self):
        malformed = {key: None for key in EVIDENCE_KEYS}
        self.assertFalse(safe_assess(malformed)["technical_evidence_valid"])

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"assessment":1,"assessment":2}', object_pairs_hook=unique_pairs)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture = MultiRoundTests("test_three_rounds_valid_but_no_authority")
        self.fixture.setUp()
        self.inputs = {
            "roundbook": self.fixture.roundbook,
            "audit_trust": self.fixture.audit_trust,
            "witness_trust": self.fixture.witness_trust,
            "logbook": self.fixture.logbook,
            "external_pins": self.fixture.pins,
            "baseline": self.fixture.baseline,
        }
        self.receipt = construct_receipt(self.inputs)

    def verify(self):
        return verify_receipt(self.receipt, self.inputs)

    def test_fully_recomputed_receipt_valid_but_denied(self):
        v = self.verify()
        self.assertTrue(v["receipt_valid"], v["errors"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["external_attestation_verified"])

    def test_report_claim_forgery_rejected(self):
        self.receipt["assessment"]["authorization"] = "ALLOW"
        self.assertIn("assessment_recomputation_mismatch", self.verify()["errors"])

    def test_check_claim_forgery_rejected(self):
        self.receipt["assessment"]["checks"]["checkpoint:0"] = False
        self.assertIn("assessment_recomputation_mismatch", self.verify()["errors"])

    def test_untrusted_receipt_checksum_forgery_rejected(self):
        self.receipt["receipt_sha256"] = "0" * 64
        self.assertIn("receipt_digest_mismatch", self.verify()["errors"])

    def test_untrusted_independent_claim_rejected(self):
        self.receipt["independently_attested"] = True
        self.assertIn("forged_independence_claim", self.verify()["errors"])

    def test_component_digest_substitution_rejected(self):
        self.receipt["input_component_sha256"]["baseline"] = "0" * 64
        self.assertIn("component_coverage_mismatch", self.verify()["errors"])

    def test_removed_component_digest_rejected(self):
        del self.receipt["input_component_sha256"]["audit_trust"]
        self.assertIn("component_coverage_mismatch", self.verify()["errors"])

    def test_changed_independent_baseline_rejected(self):
        self.inputs["baseline"]["last_payload_sha256"] = "0" * 64
        issues = self.verify()["errors"]
        self.assertIn("input_digest_mismatch", issues)
        self.assertIn("technical_assessment_failed", issues)

    def test_revoked_independent_witness_rejected(self):
        self.inputs["witness_trust"]["keys"]["w1"]["status"] = "revoked"
        self.assertIn("technical_assessment_failed", self.verify()["errors"])

    def test_deleted_middle_history_rejected(self):
        self.inputs["roundbook"]["rounds"].pop(1)
        self.assertIn("technical_assessment_failed", self.verify()["errors"])

    def test_mismatched_full_input_digest_rejected(self):
        self.receipt["input_sha256"] = "0" * 64
        self.assertIn("input_digest_mismatch", self.verify()["errors"])


if __name__ == "__main__":
    unittest.main()
