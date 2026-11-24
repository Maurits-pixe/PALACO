"""GO-20 v42: independently pinned Ed25519 fencing quorum negative regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_signed_fencing_quorum import (
    SCHEMA, TRUST_SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, verify_quorum,
)
from test_pr_recovery_fencing import FencingTests


class InvalidQuorumTests(unittest.TestCase):
    def test_missing_evidence_fails_closed(self):
        out = verify_quorum(*([None] * 8))
        self.assertFalse(out["quorum_evidence_valid"])
        self.assertEqual((out["decision"], out["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(out["failover_authorized"])

    def test_invalid_trust_denied(self):
        out = verify_quorum(*([{}] * 8))
        self.assertIn("invalid_quorum_trust", out["errors"])


class SignedQuorumTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("optional Ed25519 backend unavailable")
        base = FencingTests("test_valid_evidence_still_denies_transition")
        base.setUp()
        self.primary = base.primary
        self.candidate = base.candidate
        self.handoff_pin = base.handoff_pin
        self.transition = base.transition
        self.transition_pin = base.pin
        self.secret = {mid: Ed25519PrivateKey.generate()
                       for mid in ("controller", "observer-one", "observer-two")}
        self.trust = {"schema": TRUST_SCHEMA, "members": {}}
        for mid in self.secret:
            key = self.secret[mid].public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
            self.trust["members"][mid] = {
                "public_key_hex": key, "organization_id": "org-" + mid,
                "control_domain_id": "domain-" + mid,
                "role": "fence_controller" if mid == "controller" else "observer",
                "status": "active",
            }
        self.pin = {
            "schema": PIN_SCHEMA,
            "trust_sha256": canonical_hash(self.trust),
            "transition_sha256": canonical_hash(self.transition),
            "minimum_epoch": 8, "minimum_signatures": 2,
            "required_fence_controller": "controller",
        }
        self.signed = {"schema": SCHEMA, "votes": [
            self.sign("controller"), self.sign("observer-one"),
        ]}

    def sign(self, member_id):
        statement = {
            "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "candidate_epoch": self.transition["candidate_epoch"],
            "transition_sha256": canonical_hash(self.transition),
            "trust_sha256": canonical_hash(self.trust),
            "member_id": member_id,
            "decision": "HOLD", "authorization": "DENY",
        }
        return {
            "member_id": member_id,
            "signature_ed25519_hex": self.secret[member_id].sign(
                bytes.fromhex(canonical_hash(statement))).hex(),
        }

    def repin(self):
        self.pin["transition_sha256"] = canonical_hash(self.transition)
        self.pin["trust_sha256"] = canonical_hash(self.trust)

    def resign(self):
        self.signed["votes"] = [self.sign("controller"), self.sign("observer-one")]

    def check(self):
        return verify_quorum(self.primary, self.candidate, self.handoff_pin,
                             self.transition, self.transition_pin, self.signed,
                             self.trust, self.pin)

    def test_valid_signatures_still_hold_deny(self):
        v = self.check()
        self.assertTrue(v["quorum_evidence_valid"], v["errors"])
        self.assertEqual(v["signatures_verified"], 2)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for field in ("fence_performed", "promotion_performed", "failover_authorized",
                      "release_authorized", "merge_authorized",
                      "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[field])

    def test_forged_controller_signature(self):
        self.signed["votes"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertIn("quorum_not_met", self.check()["errors"])

    def test_forged_observer_signature(self):
        self.signed["votes"][1]["signature_ed25519_hex"] = "0" * 128
        self.assertIn("quorum_not_met", self.check()["errors"])

    def test_missing_controller_vote(self):
        self.signed["votes"][0] = self.sign("observer-two")
        self.assertIn("required_fence_controller_missing", self.check()["errors"])

    def test_duplicate_controller_vote(self):
        self.signed["votes"][1] = copy.deepcopy(self.signed["votes"][0])
        self.assertFalse(self.check()["quorum_evidence_valid"])

    def test_revoked_observer(self):
        self.trust["members"]["observer-one"]["status"] = "revoked"
        self.repin()
        self.resign()
        self.assertIn("revoked_or_invalid_voter:observer-one", self.check()["errors"])

    def test_shared_control_domain(self):
        self.trust["members"]["observer-one"]["control_domain_id"] = "domain-controller"
        self.repin()
        self.resign()
        self.assertIn("voter_custody_overlap:observer-one", self.check()["errors"])

    def test_shared_org(self):
        self.trust["members"]["observer-one"]["organization_id"] = "org-controller"
        self.repin()
        self.resign()
        self.assertIn("voter_custody_overlap:observer-one", self.check()["errors"])

    def test_public_key_substitution(self):
        self.trust["members"]["observer-one"]["public_key_hex"] = "a" * 64
        self.assertIn("independent_quorum_anchor_mismatch", self.check()["errors"])

    def test_rollback_epoch(self):
        self.pin["minimum_epoch"] = 9
        self.assertIn("quorum_epoch_rollback", self.check()["errors"])

    def test_changed_transition_unpinned(self):
        self.transition["fencing_ack"]["control_domain"] = "substituted"
        self.assertIn("independent_quorum_anchor_mismatch", self.check()["errors"])

    def test_changed_handoff_records(self):
        self.candidate.pop()
        self.assertFalse(self.check()["quorum_evidence_valid"])

    def test_boolean_minimum_quorum_rejected(self):
        self.pin["minimum_signatures"] = True
        self.assertIn("invalid_quorum_pin", self.check()["errors"])

    def test_insufficient_votes(self):
        self.pin["minimum_signatures"] = 3
        self.assertIn("quorum_not_met", self.check()["errors"])

    def test_unknown_voter(self):
        self.signed["votes"][1]["member_id"] = "stranger"
        self.assertFalse(self.check()["quorum_evidence_valid"])

    def test_wrong_fence_controller_pin(self):
        self.pin["required_fence_controller"] = "observer-two"
        self.assertIn("required_fence_controller_missing", self.check()["errors"])

    def test_invalid_controller_role(self):
        self.trust["members"]["controller"]["role"] = "observer"
        self.repin()
        self.resign()
        self.assertIn("required_fence_controller_missing", self.check()["errors"])

    def test_unknown_vote_signature_encoding(self):
        self.signed["votes"][1]["signature_ed25519_hex"] = "invalid"
        self.assertFalse(self.check()["quorum_evidence_valid"])


if __name__ == "__main__":
    unittest.main()
