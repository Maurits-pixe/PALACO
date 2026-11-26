"""GO-20 v24: independent governance, collusion indicators and HOLD/DENY tests."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_review_governance import (
    PIN_SCHEMA, PROHIBITIONS, SCHEMA, assess_governance
)
from test_pr_signed_assessment_review import SignedReviews


class MalformedGovernanceTests(unittest.TestCase):
    def test_missing_policy(self):
        v = assess_governance(None, None, None, None, None, None)
        self.assertIn("invalid_policy", v["errors"])
        self.assertFalse(v["release_authorized"])

    def test_untrusted_policy_pin(self):
        v = assess_governance(None, None, None, None, {"schema": SCHEMA}, None)
        self.assertIn("invalid_policy", v["errors"])


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        base = SignedReviews("test_valid_independent_review_stays_hold_deny")
        base.setUp()
        self.envelope = base.envelope
        self.receipt = base.receipt
        self.inputs = base.inputs
        self.trust = base.trust
        self.policy = {
            "schema": SCHEMA, "revision": 7,
            "repository": "Maurits-pixe/PALACO",
            "reviewers": {
                "evidence_reviewer": {
                    "reviewer_id": "evidence",
                    "organization_id": "org-evidence",
                    "control_domain_id": "domain-evidence",
                    "conflict_disclosed": False,
                    "governance_status": "active",
                },
                "security_reviewer": {
                    "reviewer_id": "security",
                    "organization_id": "org-security",
                    "control_domain_id": "domain-security",
                    "conflict_disclosed": False,
                    "governance_status": "active",
                },
            },
            "prohibited_capabilities": list(PROHIBITIONS),
            "declared_conflicts": [],
        }
        self.pin = {
            "schema": PIN_SCHEMA, "minimum_revision": 7,
            "policy_sha256": canonical_hash(self.policy),
        }

    def check(self):
        return assess_governance(self.envelope, self.receipt, self.inputs,
                                 self.trust, self.policy, self.pin)

    def test_valid_governance_is_still_hold_deny(self):
        v = self.check()
        self.assertTrue(v["governance_valid"], v["errors"])
        self.assertTrue(v["review_valid"])
        self.assertFalse(v["release_authorized"])
        self.assertFalse(v["merge_authorized"])
        self.assertFalse(v["deployment_authorized"])
        self.assertFalse(v["production_commit_performed"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_same_organization_detected_even_with_updated_pin(self):
        self.policy["reviewers"]["security_reviewer"]["organization_id"] = "org-evidence"
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("organization_control_overlap", self.check()["errors"])

    def test_same_key_control_domain_detected(self):
        self.policy["reviewers"]["security_reviewer"]["control_domain_id"] = "domain-evidence"
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("key_control_domain_overlap", self.check()["errors"])

    def test_declared_conflict_detected(self):
        self.policy["declared_conflicts"] = ["shared-parent"]
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("declared_conflict_present", self.check()["errors"])

    def test_reviewer_conflict_disclosure_rejected(self):
        self.policy["reviewers"]["security_reviewer"]["conflict_disclosed"] = True
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("reviewer_conflict_or_inactive:security_reviewer", self.check()["errors"])

    def test_inactive_reviewer_rejected(self):
        self.policy["reviewers"]["evidence_reviewer"]["governance_status"] = "inactive"
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("reviewer_conflict_or_inactive:evidence_reviewer", self.check()["errors"])

    def test_policy_tamper_rejected(self):
        self.policy["revision"] += 1
        self.assertIn("policy_pin_mismatch", self.check()["errors"])

    def test_policy_rollback_rejected(self):
        self.policy["revision"] = 6
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("policy_rollback", self.check()["errors"])

    def test_missing_release_prohibition_rejected(self):
        self.policy["prohibited_capabilities"].remove("merge")
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("release_prohibition_incomplete", self.check()["errors"])

    def test_duplicate_prohibition_not_accepted(self):
        self.policy["prohibited_capabilities"].append("release")
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("release_prohibition_incomplete", self.check()["errors"])

    def test_wrong_roster_signer_rejected(self):
        self.policy["reviewers"]["security_reviewer"]["reviewer_id"] = "outsider"
        self.pin["policy_sha256"] = canonical_hash(self.policy)
        self.assertIn("roster_attestation_mismatch:security_reviewer", self.check()["errors"])

    def test_revoked_cryptographic_reviewer_rejected(self):
        self.trust["reviewers"]["security"]["status"] = "revoked"
        self.assertTrue(any(x.startswith("review:") for x in self.check()["errors"]))

    def test_forged_receipt_authorization_rejected(self):
        self.receipt["assessment"]["authorization"] = "ALLOW"
        v = self.check()
        self.assertFalse(v["governance_valid"])
        self.assertFalse(v["release_authorized"])

    def test_missing_external_pin_rejected(self):
        self.pin = None
        self.assertIn("invalid_independent_policy_pin", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
