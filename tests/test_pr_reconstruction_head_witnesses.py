"""GO-20 v60: independent signed head, revocation and recovery denial tests."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_reconstruction_head_witnesses import (
    SCHEMA, TRUST_SCHEMA, REVOKE_SCHEMA, PIN_SCHEMA, HEAD_STATEMENT, assess
)
from test_pr_reconstruction_review_history import ReviewHistoryTests


class InvalidHeadTests(unittest.TestCase):
    def test_missing_all_fails_closed(self):
        v = assess(None, None, None, None, None)
        self.assertFalse(v["head_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))


class HeadWitnessTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        base = ReviewHistoryTests("test_valid_identical_histories_still_deny")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        self.sources = {
            "left": base.left, "left_pin": base.pin_left,
            "right": base.right, "right_pin": base.pin_right,
            "head": base.head,
        }
        self.secret = {mid: Ed25519PrivateKey.generate()
                       for mid in ("keeper-a", "keeper-b", "keeper-c")}
        self.trust = {"schema": TRUST_SCHEMA, "members": {}}
        for mid, secret in self.secret.items():
            self.trust["members"][mid] = {
                "public_key_hex": secret.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "organization_id": "org-" + mid,
                "domain_id": "domain-" + mid,
                "status": "active",
            }
        self.revocations = {"schema": REVOKE_SCHEMA, "entries": []}
        self.pin = {
            "schema": PIN_SCHEMA,
            "v59_sources_sha256": canonical_hash(self.sources),
            "head_sha256": canonical_hash(self.sources["head"]),
            "witness_trust_sha256": canonical_hash(self.trust),
            "revocations_sha256": canonical_hash(self.revocations),
            "minimum_last_round": 31,
            "minimum_witnesses": 2,
        }
        self.evidence = {"schema": SCHEMA, "witnesses": [], "decisions": [
            {"observer": side,
             "view_sha256": canonical_hash(self.sources[side]),
             "decision": "HOLD", "authorization": "DENY"}
            for side in ("left", "right")
        ]}
        self.resign()

    def signature(self, mid):
        statement = {
            "schema": HEAD_STATEMENT,
            "repository": "Maurits-pixe/PALACO",
            "witness_id": mid,
            "v59_sources_sha256": self.pin["v59_sources_sha256"],
            "head_sha256": self.pin["head_sha256"],
            "revocations_sha256": self.pin["revocations_sha256"],
            "witness_trust_sha256": self.pin["witness_trust_sha256"],
            "minimum_last_round": self.pin["minimum_last_round"],
            "decision": "HOLD", "authorization": "DENY",
        }
        return self.secret[mid].sign(bytes.fromhex(canonical_hash(statement))).hex()

    def resign(self):
        self.evidence["witnesses"] = [
            {"witness_id": mid, "signature_ed25519_hex": self.signature(mid)}
            for mid in ("keeper-a", "keeper-b")]

    def check(self):
        return assess(self.sources, self.evidence, self.trust,
                      self.revocations, self.pin)

    def test_two_signed_anchors_remain_hold(self):
        v = self.check()
        self.assertTrue(v["head_evidence_valid"], v["errors"])
        self.assertEqual((v["head_witnesses_verified"], v["decisions_verified"]), (2, 2))
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for k in ("reviewer_revocations_enforced_in_production",
                  "restoration_performed", "recovery_authorized",
                  "trust_registry_promoted", "failover_authorized",
                  "merge_authorized", "deployment_authorized",
                  "production_commit_performed"):
            self.assertFalse(v[k])

    def test_forged_signature(self):
        self.evidence["witnesses"][0]["signature_ed25519_hex"] = "0"*128
        self.assertIn("invalid_head_witness_signature:0", self.check()["errors"])

    def test_duplicate_keeper(self):
        self.evidence["witnesses"][1] = copy.deepcopy(self.evidence["witnesses"][0])
        self.assertIn("duplicate_or_unknown_head_witness:1", self.check()["errors"])

    def test_other_signer_signature_replay(self):
        self.evidence["witnesses"][1]["signature_ed25519_hex"] = (
            self.evidence["witnesses"][0]["signature_ed25519_hex"])
        self.assertIn("invalid_head_witness_signature:1", self.check()["errors"])

    def test_unknown_keeper(self):
        self.evidence["witnesses"][0]["witness_id"] = "unknown"
        self.assertFalse(self.check()["head_evidence_valid"])

    def test_revoked_keeper(self):
        self.trust["members"]["keeper-b"]["status"] = "revoked"
        self.pin["witness_trust_sha256"] = canonical_hash(self.trust)
        self.resign()
        self.assertIn("invalid_head_witness:1", self.check()["errors"])

    def test_shared_organization(self):
        self.trust["members"]["keeper-b"]["organization_id"] = "org-keeper-a"
        self.pin["witness_trust_sha256"] = canonical_hash(self.trust)
        self.resign()
        self.assertIn("overlapping_head_witness_custody:1", self.check()["errors"])

    def test_shared_domain(self):
        self.trust["members"]["keeper-b"]["domain_id"] = "domain-keeper-a"
        self.pin["witness_trust_sha256"] = canonical_hash(self.trust)
        self.resign()
        self.assertIn("overlapping_head_witness_custody:1", self.check()["errors"])

    def test_public_key_substitution(self):
        self.trust["members"]["keeper-a"]["public_key_hex"] = "f"*64
        self.assertIn("external_anchor_mismatch", self.check()["errors"])

    def test_revoked_reviewer_still_present(self):
        reviewer = self.base.left["rounds"][1]["sources"]["reviewers"]["members"]["review-a"]
        self.revocations["entries"].append({
            "reviewer_id": "review-a",
            "public_key_hex": reviewer["public_key_hex"],
            "effective_round": 31,
        })
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.resign()
        self.assertIn("revoked_reviewer_still_trusted:31:review-a", self.check()["errors"])

    def test_revocation_removed_from_external_anchor(self):
        self.revocations["entries"].append({
            "reviewer_id": "review-a", "public_key_hex": "f"*64,
            "effective_round": 30,
        })
        self.assertIn("external_anchor_mismatch", self.check()["errors"])

    def test_duplicate_revocation(self):
        record = {"reviewer_id": "review-a",
                  "public_key_hex": "f"*64, "effective_round": 30}
        self.revocations["entries"] = [record, copy.deepcopy(record)]
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.resign()
        self.assertIn("duplicate_revocation:1", self.check()["errors"])

    def test_invalid_boolean_revocation_round(self):
        self.revocations["entries"].append({
            "reviewer_id": "review-a", "public_key_hex": "f"*64,
            "effective_round": True})
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.resign()
        self.assertIn("invalid_revocation:0", self.check()["errors"])

    def test_recovery_decision_go_denied(self):
        self.evidence["decisions"][1]["decision"] = "GO"
        self.assertIn("unauthorized_recovery_decision:1", self.check()["errors"])

    def test_recovery_authorization_grant_denied(self):
        self.evidence["decisions"][1]["authorization"] = "ALLOW"
        self.assertIn("unauthorized_recovery_decision:1", self.check()["errors"])

    def test_recovery_view_mismatch(self):
        self.evidence["decisions"][0]["view_sha256"] = "f"*64
        self.assertIn("conflicting_recovery_decision_view:0", self.check()["errors"])

    def test_duplicate_observer_decision(self):
        self.evidence["decisions"][1]["observer"] = "left"
        self.assertIn("missing_or_duplicate_decision:1", self.check()["errors"])

    def test_v59_history_broken(self):
        self.sources["right"]["rounds"].pop()
        self.pin["v59_sources_sha256"] = canonical_hash(self.sources)
        self.resign()
        self.assertTrue(any(e.startswith("v59:") for e in self.check()["errors"]))

    def test_stale_recovery_head(self):
        self.pin["minimum_last_round"] = 32
        self.resign()
        self.assertIn("history_head_rollback", self.check()["errors"])

    def test_boolean_quorum_denied(self):
        self.pin["minimum_witnesses"] = True
        self.assertIn("invalid_independent_head_pin", self.check()["errors"])

    def test_unpinned_evidence_cannot_change_history(self):
        self.sources["head"]["expected_view_sha256"] = "a"*64
        self.assertIn("external_anchor_mismatch", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
