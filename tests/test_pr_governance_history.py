"""GO-20 v25: signed reviewer-policy continuity and anti-rollback regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_governance_history import (
    SCHEMA, PIN_SCHEMA, CONTROLLER_TRUST_SCHEMA, TRANSITION_SCHEMA, verify_history,
)
from pr_signed_assessment_review import STATEMENT_SCHEMA
from test_pr_review_governance import GovernanceTests


class InvalidHistoryTests(unittest.TestCase):
    def test_no_history(self):
        self.assertIn("invalid_governance_history", verify_history(None, None, None)["errors"])

    def test_no_independent_pin(self):
        data = {"schema": SCHEMA, "snapshots": [{}, {}], "transitions": [{}]}
        self.assertIn("invalid_independent_history_pin",
                      verify_history(data, None, None)["errors"])


class GovernanceHistoryTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("cryptography backend missing")
        self.Ed25519PrivateKey = Ed25519PrivateKey
        self.Encoding = Encoding
        self.PublicFormat = PublicFormat
        base = GovernanceTests("test_valid_governance_is_still_hold_deny")
        base.setUp()
        self.controller = Ed25519PrivateKey.generate()
        self.controller_pub = self.public(self.controller)
        self.trust = {"schema": CONTROLLER_TRUST_SCHEMA, "controllers": {
            "governance-controller": {
                "public_key_hex": self.controller_pub, "status": "active",
            }
        }}
        initial = {"policy": copy.deepcopy(base.policy),
                   "review": copy.deepcopy(base.envelope),
                   "receipt": copy.deepcopy(base.receipt),
                   "inputs": copy.deepcopy(base.inputs),
                   "reviewer_trust": copy.deepcopy(base.trust)}
        next_state = copy.deepcopy(initial)
        next_state["policy"]["revision"] = 8
        self.history = {"schema": SCHEMA, "snapshots": [initial, next_state],
                        "transitions": []}
        self.history["transitions"] = [self.transition([], 0)]
        self.pin = self.pin_history()

    def public(self, key):
        return key.public_key().public_bytes(self.Encoding.Raw,
                                             self.PublicFormat.Raw).hex()

    def transition(self, changes, at=0):
        old = self.history["snapshots"][at]["policy"]
        new = self.history["snapshots"][at + 1]["policy"]
        data = {
            "from_revision": old["revision"],
            "to_revision": new["revision"],
            "from_policy_sha256": canonical_hash(old),
            "to_policy_sha256": canonical_hash(new),
            "changed_roles": changes,
            "controller_id": "governance-controller",
        }
        statement = {"schema": TRANSITION_SCHEMA, **data}
        return {**data, "signature_ed25519_hex":
                self.controller.sign(bytes.fromhex(canonical_hash(statement))).hex()}

    def pin_history(self):
        return {
            "schema": PIN_SCHEMA,
            "first_revision": self.history["snapshots"][0]["policy"]["revision"],
            "first_policy_sha256": canonical_hash(self.history["snapshots"][0]["policy"]),
            "last_revision": self.history["snapshots"][-1]["policy"]["revision"],
            "last_policy_sha256": canonical_hash(self.history["snapshots"][-1]["policy"]),
        }

    def verify(self):
        return verify_history(self.history, self.pin, self.trust)

    def rotate_security_reviewer(self):
        change = self.history["snapshots"][1]
        new_key = self.Ed25519PrivateKey.generate()
        new_id = "security-rotated"
        change["policy"]["reviewers"]["security_reviewer"]["reviewer_id"] = new_id
        change["policy"]["reviewers"]["security_reviewer"]["control_domain_id"] = "new-control-domain"
        change["reviewer_trust"]["reviewers"][new_id] = {
            "public_key_hex": self.public(new_key),
            "status": "active", "role": "security_reviewer",
        }
        att = {
            "schema": STATEMENT_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "receipt_sha256": change["receipt"]["receipt_sha256"],
            "role": "security_reviewer",
            "reviewer_id": new_id,
            "decision": "HOLD",
            "authorization": "DENY",
        }
        change["review"]["attestations"][1] = {
            "role": "security_reviewer",
            "reviewer_id": new_id,
            "signature_ed25519_hex": new_key.sign(
                bytes.fromhex(canonical_hash(att))).hex(),
        }
        self.history["transitions"][0] = self.transition(["security_reviewer"])
        self.pin = self.pin_history()

    def test_valid_unchanged_history_still_denies(self):
        output = self.verify()
        self.assertTrue(output["history_valid"], output["errors"])
        self.assertEqual(output["versions_checked"], 2)
        self.assertEqual(output["reviewer_rotations_verified"], 0)
        self.assertEqual((output["decision"], output["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(output["release_authorized"])
        self.assertFalse(output["merge_authorized"])

    def test_controlled_one_role_rotation(self):
        self.rotate_security_reviewer()
        output = self.verify()
        self.assertTrue(output["history_valid"], output["errors"])
        self.assertEqual(output["reviewer_rotations_verified"], 1)

    def test_unauthorized_reviewer_change(self):
        self.rotate_security_reviewer()
        change = self.history["transitions"][0]
        change["changed_roles"] = []
        change["signature_ed25519_hex"] = self.transition([])["signature_ed25519_hex"]
        self.assertIn("unreported_reviewer_change:0", self.verify()["errors"])

    def test_two_reviewers_change_together_denied(self):
        self.rotate_security_reviewer()
        self.history["transitions"][0]["changed_roles"] = [
            "evidence_reviewer", "security_reviewer"
        ]
        self.assertIn("invalid_rotation_declaration:0", self.verify()["errors"])

    def test_snapshot_revision_gap(self):
        self.history["snapshots"][1]["policy"]["revision"] = 9
        self.assertIn("policy_revision_gap:1", self.verify()["errors"])

    def test_historical_policy_tamper(self):
        self.history["snapshots"][0]["policy"]["declared_conflicts"] = ["tampered"]
        self.assertIn("independent_first_policy_mismatch", self.verify()["errors"])

    def test_pin_rollback(self):
        self.pin["last_revision"] = 7
        self.assertIn("invalid_independent_history_pin_fields", self.verify()["errors"])

    def test_transition_tampering(self):
        self.history["transitions"][0]["to_policy_sha256"] = "0" * 64
        self.assertIn("transition_link_mismatch:0", self.verify()["errors"])

    def test_invalid_controller_signature(self):
        self.history["transitions"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(e.startswith("transition_signature:0:") for e in self.verify()["errors"]))

    def test_revoked_controller(self):
        self.trust["controllers"]["governance-controller"]["status"] = "revoked"
        self.assertIn("untrusted_or_revoked_controller:0", self.verify()["errors"])

    def test_controller_reviewer_key_overlap(self):
        self.trust["controllers"]["governance-controller"]["public_key_hex"] = (
            self.history["snapshots"][0]["reviewer_trust"]["reviewers"]["evidence"]["public_key_hex"]
        )
        self.assertIn("controller_reviewer_key_overlap:0", self.verify()["errors"])

    def test_prohibitions_cannot_change(self):
        new = self.history["snapshots"][1]["policy"]
        new["prohibited_capabilities"].remove("merge")
        self.pin = self.pin_history()
        self.history["transitions"][0] = self.transition([])
        output = self.verify()
        self.assertIn("prohibition_policy_changed:0", output["errors"])

    def test_missing_transition_rejected(self):
        self.history["transitions"] = []
        self.assertIn("invalid_governance_history", self.verify()["errors"])

    def test_invalid_next_review_attestation(self):
        self.history["snapshots"][1]["review"]["attestations"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(e.startswith("snapshot:1:review:signature") for e in self.verify()["errors"]))


if __name__ == "__main__":
    unittest.main()
