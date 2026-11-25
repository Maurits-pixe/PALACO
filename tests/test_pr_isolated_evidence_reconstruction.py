"""GO-20 v58: isolated full-content comparison and independent audit review."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pr_audit_integrity import canonical_hash
from pr_isolated_evidence_reconstruction import (
    SCHEMA, PIN_SCHEMA, REVIEW_SCHEMA, REPORT_SCHEMA, assess,
)
from test_pr_revocation_archive_challenges import ArchiveChallengeTests


class InvalidReconstructionTests(unittest.TestCase):
    def test_null_sources_denied(self):
        v = assess(None, None, None, None, None)
        self.assertFalse(v["isolated_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["production_restoration_performed"])


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        base = ArchiveChallengeTests("test_complete_claims_still_hold_deny")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        self.v57 = {
            "v56_sources": base.sources,
            "challenges": base.challenges,
            "independent_pin": base.pin,
        }
        self.secrets = {mid: Ed25519PrivateKey.generate()
                        for mid in ("review-a", "review-b", "review-c")}
        self.trust = {"schema": REVIEW_SCHEMA, "members": {}}
        for mid, sk in self.secrets.items():
            self.trust["members"][mid] = {
                "public_key_hex": sk.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "organization_id": "org-" + mid,
                "domain_id": "domain-" + mid,
                "status": "active",
            }
        self.reconstruction = {"schema": SCHEMA, "epochs": [], "review_signatures": []}
        for i, item in enumerate(base.sources["custody"]["epochs"]):
            self.reconstruction["epochs"].append({
                "epoch": item["epoch"],
                "nonce_sha256": base.challenges["epochs"][i]["nonce_sha256"],
                "copies": [{"custodian_id": cid,
                            "checkpoint": copy.deepcopy(item["checkpoint"])}
                           for cid in ("archive-a", "archive-b")],
            })
        self.pin = {
            "schema": PIN_SCHEMA,
            "v57_sha256": canonical_hash(self.v57),
            "copies_sha256": "0" * 64,
            "reviewer_trust_sha256": canonical_hash(self.trust),
            "minimum_epoch": 21, "minimum_copies": 2,
            "minimum_reviews": 2,
        }
        self.repin()
        self.resign()

    def repin(self):
        self.pin["copies_sha256"] = canonical_hash({
            "schema": SCHEMA, "epochs": self.reconstruction["epochs"]})

    def sign(self, mid, epoch_count=2, copy_count=4):
        statement = {
            "schema": REPORT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "v57_sha256": self.pin["v57_sha256"],
            "copies_sha256": self.pin["copies_sha256"],
            "reviewer_trust_sha256": self.pin["reviewer_trust_sha256"],
            "epoch_count": epoch_count, "copy_count": copy_count,
            "decision": "HOLD", "authorization": "DENY",
            "reviewer_id": mid,
        }
        return self.secrets[mid].sign(bytes.fromhex(canonical_hash(statement))).hex()

    def resign(self):
        self.reconstruction["review_signatures"] = [
            {"reviewer_id": mid, "signature_ed25519_hex": self.sign(mid)}
            for mid in ("review-a", "review-b")]

    def check(self, now=120):
        return assess(self.v57, self.reconstruction, self.trust, self.pin, now)

    def test_complete_memory_reconstruction_still_deny(self):
        result = self.check()
        self.assertTrue(result["isolated_evidence_valid"], result["errors"])
        self.assertEqual((result["epochs_compared"], result["copies_compared"],
                          result["reviewer_signatures_verified"]), (2, 4, 2))
        for key in ("remote_media_read_performed", "live_availability_verified",
                    "production_restoration_performed",
                    "independent_media_custody_verified", "challenge_reopened",
                    "failover_authorized", "merge_authorized",
                    "deployment_authorized", "production_commit_performed"):
            self.assertFalse(result[key])

    def test_missing_epoch_copy(self):
        self.reconstruction["epochs"].pop()
        self.repin()
        self.assertIn("invalid_reconstruction_bundle", self.check()["errors"])

    def test_missing_one_custodian_copy(self):
        self.reconstruction["epochs"][0]["copies"].pop()
        self.repin()
        self.assertIn("missing_or_invalid_epoch_copy:0", self.check()["errors"])

    def test_modified_historical_entry(self):
        self.reconstruction["epochs"][1]["copies"][0]["checkpoint"]["epoch"] = 99
        self.repin()
        self.assertIn("restored_content_mismatch:1:archive-a", self.check()["errors"])

    def test_deleted_historical_signature(self):
        self.reconstruction["epochs"][0]["copies"][1]["checkpoint"]["signatures"].pop()
        self.repin()
        self.assertIn("restored_content_mismatch:0:archive-b", self.check()["errors"])

    def test_duplicate_custodian_copy(self):
        self.reconstruction["epochs"][0]["copies"][1] = copy.deepcopy(
            self.reconstruction["epochs"][0]["copies"][0])
        self.repin()
        self.assertIn("unknown_or_duplicate_restoration_copy:0:1", self.check()["errors"])

    def test_non_receipted_custodian(self):
        self.reconstruction["epochs"][0]["copies"][1]["custodian_id"] = "archive-c"
        self.repin()
        self.assertIn("unknown_or_duplicate_restoration_copy:0:1", self.check()["errors"])

    def test_wrong_nonce(self):
        self.reconstruction["epochs"][0]["nonce_sha256"] = "f"*64
        self.repin()
        self.assertIn("missing_or_invalid_epoch_copy:0", self.check()["errors"])

    def test_epoch_rollback(self):
        self.pin["minimum_epoch"] = 22
        self.assertIn("incomplete_or_rollback_reconstruction", self.check()["errors"])

    def test_unchanged_external_pin_rejects_copy_change(self):
        self.reconstruction["epochs"][0]["copies"][0]["checkpoint"]["epoch"] = 99
        self.assertIn("independent_reconstruction_anchor_mismatch", self.check()["errors"])

    def test_replaced_reviewer_key_denied(self):
        self.trust["members"]["review-a"]["public_key_hex"] = "f"*64
        self.assertIn("independent_reconstruction_anchor_mismatch", self.check()["errors"])

    def test_forged_review_signature(self):
        self.reconstruction["review_signatures"][0]["signature_ed25519_hex"] = "0"*128
        self.assertIn("invalid_review_signature:0:review-a", self.check()["errors"])

    def test_duplicate_reviewer(self):
        self.reconstruction["review_signatures"][1] = copy.deepcopy(
            self.reconstruction["review_signatures"][0])
        self.assertIn("unknown_or_duplicate_reviewer:1", self.check()["errors"])

    def test_shared_review_domain(self):
        self.trust["members"]["review-b"]["domain_id"] = "domain-review-a"
        self.pin["reviewer_trust_sha256"] = canonical_hash(self.trust)
        self.resign()
        self.assertIn("overlapping_reviewer_custody:1:review-b", self.check()["errors"])

    def test_revoked_reviewer(self):
        self.trust["members"]["review-b"]["status"] = "revoked"
        self.pin["reviewer_trust_sha256"] = canonical_hash(self.trust)
        self.resign()
        self.assertIn("invalid_reviewer:1:review-b", self.check()["errors"])

    def test_stricter_reviewer_quorum(self):
        self.pin["minimum_reviews"] = 3
        self.assertIn("independent_review_quorum_missing", self.check()["errors"])

    def test_boolean_review_quorum(self):
        self.pin["minimum_reviews"] = True
        self.assertIn("invalid_independent_reconstruction_pin", self.check()["errors"])

    def test_expired_underlying_challenge(self):
        self.assertTrue(any(e.startswith("v57:") for e in self.check(151)["errors"]))

    def test_forged_underlying_retrieval_signature(self):
        self.base.challenges["epochs"][0]["responses"][0]["signature_ed25519_hex"] = "0"*128
        self.pin["v57_sha256"] = canonical_hash(self.v57)
        self.assertTrue(any(e.startswith("v57:") for e in self.check()["errors"]))

    def test_missing_original_archive(self):
        self.base.sources["custody"]["epochs"].pop()
        self.pin["v57_sha256"] = canonical_hash(self.v57)
        self.assertFalse(self.check()["isolated_evidence_valid"])

    def test_signed_review_not_sufficient_if_copies_changed(self):
        self.reconstruction["epochs"][0]["copies"][0]["checkpoint"]["epoch"] = 98
        self.repin()
        self.resign()
        self.assertIn("restored_content_mismatch:0:archive-a", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
