"""GO-20 v31: independently pinned observer receipts and custody boundaries."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_observer_anchor_custody import (
    SCHEMA, TRUST_SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, verify_anchors,
)
from test_pr_attestation_multiview import MultiViewTests


class MissingObserverEvidenceTests(unittest.TestCase):
    def test_missing_bundle_is_denied(self):
        v = verify_anchors(None, None, None, None, None)
        self.assertFalse(v["anchors_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["release_authorized"])

    def test_missing_registry_denied(self):
        v = verify_anchors({"schema": "palaco.go20-attestation-multiview.v1", "views": []}, {},
                           {"schema": SCHEMA, "anchors": [{}, {}]}, None, None)
        self.assertIn("invalid_observer_custody_registry", v["errors"])


class ObserverCustodyTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("optional cryptography backend not available")
        base = MultiViewTests("test_identical_verified_histories_stay_hold")
        base.setUp()
        self.views = base.package
        self.history_pins = base.pins
        self.private = {
            vid: Ed25519PrivateKey.generate() for vid in ("observer-a", "observer-b")
        }
        self.trust = {"schema": TRUST_SCHEMA, "observers": {}}
        self.signed = {"schema": SCHEMA, "anchors": []}
        self.heads = {"schema": PIN_SCHEMA, "heads": {}}
        for vid in ("observer-a", "observer-b"):
            private = self.private[vid]
            self.trust["observers"][vid] = {
                "public_key_hex": private.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "status": "active",
                "organization_id": "org-" + vid,
                "control_domain_id": "domain-" + vid,
            }
            self.signed["anchors"].append(self.sign(vid))
        self.repin()

    def sign(self, vid, epoch=7):
        record = self.trust["observers"][vid]
        statement = {
            "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "view_id": vid, "epoch": epoch,
            "history_pin_sha256": canonical_hash(self.history_pins["views"][vid]),
            "organization_id": record["organization_id"],
            "control_domain_id": record["control_domain_id"],
            "decision": "HOLD", "authorization": "DENY",
        }
        return {"view_id": vid, "statement": statement,
                "signature_ed25519_hex": self.private[vid].sign(
                    bytes.fromhex(canonical_hash(statement))).hex()}

    def repin(self):
        self.heads["heads"] = {
            entry["view_id"]: {
                "minimum_epoch": 7,
                "receipt_sha256": canonical_hash(entry),
            }
            for entry in self.signed["anchors"]
        }

    def check(self):
        return verify_anchors(self.views, self.history_pins, self.signed,
                              self.trust, self.heads)

    def test_two_valid_independent_views_remain_hold_deny(self):
        v = self.check()
        self.assertTrue(v["anchors_valid"], v["errors"])
        self.assertEqual(v["observers_verified"], 2)
        self.assertTrue(v["multiview_verdict"]["views_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for key in ("release_authorized", "merge_authorized",
                    "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[key])

    def test_same_org_rejected_even_when_reattested(self):
        self.trust["observers"]["observer-b"]["organization_id"] = "org-observer-a"
        self.signed["anchors"][1] = self.sign("observer-b")
        self.repin()
        self.assertIn("observer_custody_overlap:observer-b", self.check()["errors"])

    def test_shared_control_domain_rejected(self):
        self.trust["observers"]["observer-b"]["control_domain_id"] = "domain-observer-a"
        self.signed["anchors"][1] = self.sign("observer-b")
        self.repin()
        self.assertIn("observer_custody_overlap:observer-b", self.check()["errors"])

    def test_shared_public_key_rejected(self):
        self.trust["observers"]["observer-b"]["public_key_hex"] = (
            self.trust["observers"]["observer-a"]["public_key_hex"]
        )
        self.assertIn("observer_custody_overlap:observer-b", self.check()["errors"])

    def test_revoked_observer_rejected(self):
        self.trust["observers"]["observer-a"]["status"] = "revoked"
        self.assertIn("invalid_or_revoked_observer:observer-a", self.check()["errors"])

    def test_pin_tamper_rejected(self):
        self.heads["heads"]["observer-b"]["receipt_sha256"] = "0" * 64
        self.assertIn("independent_observer_head_mismatch:observer-b", self.check()["errors"])

    def test_epoch_rollback_denied(self):
        self.heads["heads"]["observer-a"]["minimum_epoch"] = 8
        self.assertIn("observer_epoch_rollback:observer-a", self.check()["errors"])

    def test_signature_forgery_denied(self):
        self.signed["anchors"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(x.startswith("observer_signature:observer-a:") for x in self.check()["errors"]))

    def test_changed_history_anchor_denied(self):
        self.history_pins["views"]["observer-b"]["last_attestation_sha256"] = "0" * 64
        self.assertFalse(self.check()["anchors_valid"])

    def test_missing_independent_observer_head(self):
        self.heads["heads"].pop("observer-a")
        self.assertIn("observer_coverage_or_identity_mismatch", self.check()["errors"])

    def test_duplicate_observer_receipt(self):
        self.signed["anchors"][1] = copy.deepcopy(self.signed["anchors"][0])
        self.assertIn("observer_coverage_or_identity_mismatch", self.check()["errors"])

    def test_wrong_authority_statement_denied(self):
        self.signed["anchors"][0]["statement"]["authorization"] = "ALLOW"
        self.assertIn("observer_identity_or_authority_mismatch:observer-a", self.check()["errors"])

    def test_corrupt_multiview_signature_denied(self):
        self.views["views"][1]["history"]["entries"][0]["envelope"]["signature_ed25519_hex"] = "0" * 128
        self.assertFalse(self.check()["anchors_valid"])

    def test_wrong_repository_denied(self):
        self.signed["anchors"][1]["statement"]["repository"] = "other/repo"
        self.assertIn("observer_identity_or_authority_mismatch:observer-b", self.check()["errors"])

    def test_non_json_structure_denied(self):
        self.trust["observers"]["observer-a"]["extras"] = {1, 2}
        self.assertFalse(self.check()["anchors_valid"])


if __name__ == "__main__":
    unittest.main()
