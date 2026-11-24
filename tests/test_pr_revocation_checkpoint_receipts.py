"""GO-20 v56: historical checkpoint custody receipts and negative evidence."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_revocation_checkpoint_receipts import (
    SCHEMA, TRUST_SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, assess,
)
from test_pr_revocation_history_consensus import RevocationHistoryTests


class InvalidCustodyTests(unittest.TestCase):
    def test_all_missing_remains_hold_deny(self):
        v = assess(None, None, None, None)
        self.assertFalse(v["receipt_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["publication_performed"])


class RevocationReceiptTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        source = RevocationHistoryTests("test_two_observers_valid_still_deny")
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.source = source
        self.sources = {
            "left": source.left, "left_pin": source.left_pin,
            "right": source.right, "right_pin": source.right_pin,
            "external": source.external, "v54_sources": source.v54,
        }
        self.secret = {mid: Ed25519PrivateKey.generate()
                       for mid in ("archive-a", "archive-b", "archive-c")}
        self.trust = {"schema": TRUST_SCHEMA, "custodians": {}}
        for mid, secret in self.secret.items():
            self.trust["custodians"][mid] = {
                "public_key_hex": secret.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "organization_id": "org-" + mid,
                "domain_id": "domain-" + mid,
                "status": "active",
            }
        self.pin = {
            "schema": PIN_SCHEMA,
            "view_sha256": canonical_hash(source.left),
            "head_sha256": canonical_hash(source.external),
            "trust_sha256": canonical_hash(self.trust),
            "first_epoch": 20, "last_epoch": 21, "quorum": 2,
        }
        self.custody = {"schema": SCHEMA, "epochs": []}
        for epoch in source.left["epochs"]:
            record = {"epoch": epoch["epoch"], "checkpoint": copy.deepcopy(epoch),
                      "receipts": []}
            for mid in ("archive-a", "archive-b"):
                record["receipts"].append({
                    "custodian_id": mid, "signature_ed25519_hex": self.sign(epoch, mid),
                })
            self.custody["epochs"].append(record)

    def sign(self, epoch, mid):
        statement = {
            "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "epoch": epoch["epoch"],
            "checkpoint_sha256": canonical_hash(epoch),
            "previous_sha256": epoch["previous_sha256"],
            "history_sha256": self.pin["view_sha256"],
            "head_sha256": self.pin["head_sha256"],
            "trust_sha256": self.pin["trust_sha256"],
            "custodian_id": mid,
            "decision": "HOLD", "authorization": "DENY",
        }
        return self.secret[mid].sign(bytes.fromhex(canonical_hash(statement))).hex()

    def check(self):
        return assess(self.sources, self.custody, self.trust, self.pin)

    def test_valid_archived_claims_still_deny(self):
        r = self.check()
        self.assertTrue(r["receipt_evidence_valid"], r["errors"])
        self.assertEqual((r["epochs_verified"], r["receipts_verified"]), (2, 4))
        for field in ("remote_storage_verified", "publication_performed",
                      "missing_history_recovered", "revocation_enforced_in_production",
                      "trust_registry_promoted", "failover_authorized",
                      "merge_authorized", "deployment_authorized",
                      "production_commit_performed"):
            self.assertFalse(r[field])

    def test_missing_epoch(self):
        self.custody["epochs"].pop()
        self.assertFalse(self.check()["receipt_evidence_valid"])

    def test_missing_one_receipt(self):
        self.custody["epochs"][0]["receipts"].pop()
        self.assertIn("missing_checkpoint_or_receipts:0", self.check()["errors"])

    def test_tampered_epoch_copy(self):
        self.custody["epochs"][1]["checkpoint"]["epoch"] = 99
        self.assertIn("divergent_checkpoint_copy:1", self.check()["errors"])

    def test_forged_signature(self):
        self.custody["epochs"][0]["receipts"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertIn("invalid_custody_signature:0:archive-a", self.check()["errors"])

    def test_duplicate_custodian(self):
        self.custody["epochs"][0]["receipts"][1] = copy.deepcopy(
            self.custody["epochs"][0]["receipts"][0])
        self.assertIn("duplicate_or_unknown_custodian:0:1", self.check()["errors"])

    def test_replay_prior_epoch_receipt(self):
        self.custody["epochs"][1]["receipts"][0]["signature_ed25519_hex"] = (
            self.custody["epochs"][0]["receipts"][0]["signature_ed25519_hex"])
        self.assertIn("invalid_custody_signature:1:archive-a", self.check()["errors"])

    def test_unknown_custodian(self):
        self.custody["epochs"][0]["receipts"][0]["custodian_id"] = "outsider"
        self.assertFalse(self.check()["receipt_evidence_valid"])

    def test_revoked_custodian(self):
        self.trust["custodians"]["archive-b"]["status"] = "revoked"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.assertIn("invalid_custodian:0:archive-b", self.check()["errors"])

    def test_shared_organization(self):
        self.trust["custodians"]["archive-b"]["organization_id"] = "org-archive-a"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.assertIn("overlapping_custody:0:archive-b", self.check()["errors"])

    def test_shared_domain(self):
        self.trust["custodians"]["archive-b"]["domain_id"] = "domain-archive-a"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.assertIn("overlapping_custody:0:archive-b", self.check()["errors"])

    def test_external_trust_substitution(self):
        self.trust["custodians"]["archive-b"]["public_key_hex"] = "f" * 64
        self.assertIn("independent_custody_anchor_mismatch", self.check()["errors"])

    def test_head_rollback(self):
        self.pin["last_epoch"] = 20
        self.assertIn("invalid_independent_custody_pin", self.check()["errors"])

    def test_first_epoch_rollback(self):
        self.pin["first_epoch"] = 19
        self.assertFalse(self.check()["receipt_evidence_valid"])

    def test_boolean_quorum(self):
        self.pin["quorum"] = True
        self.assertIn("invalid_independent_custody_pin", self.check()["errors"])

    def test_raised_quorum(self):
        self.pin["quorum"] = 3
        self.assertIn("missing_publication_receipts:0", self.check()["errors"])

    def test_external_head_mismatch(self):
        self.pin["head_sha256"] = "a" * 64
        self.assertIn("independent_custody_anchor_mismatch", self.check()["errors"])

    def test_original_v55_history_missing(self):
        self.sources["right"]["epochs"].pop()
        self.assertTrue(any(x.startswith("v55:") for x in self.check()["errors"]))

    def test_original_v54_witness_missing(self):
        self.source.v54["testimony"]["transitions"][0]["signatures"].pop()
        self.assertTrue(any(x.startswith("v55:") for x in self.check()["errors"]))

    def test_custody_does_not_replace_missing_original_epoch(self):
        self.sources["left"]["epochs"].pop()
        self.pin["view_sha256"] = canonical_hash(self.sources["left"])
        self.assertFalse(self.check()["receipt_evidence_valid"])


if __name__ == "__main__":
    unittest.main()
