"""GO-20 v52: independently signed custody receipts and missing-history tests."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_ledger_history_receipts import (
    SCHEMA, TRUST_SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, assess,
)
from test_pr_challenge_ledger_history import LedgerHistoryTests


class InvalidArchiveTests(unittest.TestCase):
    def test_null_sources_fail_closed(self):
        result = assess(*([None] * 8))
        self.assertFalse(result["archive_evidence_valid"])
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(result["missing_history_recovered"])


class LedgerReceiptTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        base = LedgerHistoryTests("test_valid_two_histories_still_hold")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        self.private = {
            mid: Ed25519PrivateKey.generate()
            for mid in ("archive-a", "archive-b", "archive-c")
        }
        self.trust = {"schema": TRUST_SCHEMA, "custodians": {}}
        for mid, sk in self.private.items():
            self.trust["custodians"][mid] = {
                "public_key_hex": sk.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "organization_id": "organization-" + mid,
                "domain_id": "domain-" + mid,
                "status": "active",
            }
        self.pin = {
            "schema": PIN_SCHEMA,
            "trust_sha256": canonical_hash(self.trust),
            "history_sha256": canonical_hash(base.left),
            "head_sha256": canonical_hash(base.head),
            "minimum_receipts": 2,
            "minimum_last_sequence": 3,
        }
        self.archive = {"schema": SCHEMA, "receipts": []}
        for mid in ("archive-a", "archive-b"):
            self.archive["receipts"].append({
                "custodian_id": mid,
                "history": copy.deepcopy(base.left),
                "signature_ed25519_hex": self.sign(mid),
            })

    def sign(self, mid):
        b = self.base
        statement = {
            "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "custodian_id": mid,
            "history_sha256": self.pin["history_sha256"],
            "head_sha256": self.pin["head_sha256"],
            "first_sequence": b.pin_left["first_sequence"],
            "last_sequence": b.pin_left["last_sequence"],
            "trust_sha256": self.pin["trust_sha256"],
            "decision": "HOLD", "authorization": "DENY",
        }
        return self.private[mid].sign(
            bytes.fromhex(canonical_hash(statement))).hex()

    def check(self):
        b = self.base
        return assess(b.left, b.pin_left, b.right, b.pin_right, b.head,
                      self.archive, self.trust, self.pin)

    def test_verified_receipts_still_hold_deny(self):
        v = self.check()
        self.assertTrue(v["archive_evidence_valid"], v["errors"])
        self.assertEqual(v["receipts_verified"], 2)
        for name in ("external_storage_verified", "missing_history_recovered",
                     "ledger_promoted", "challenge_reopened", "failover_authorized",
                     "merge_authorized", "deployment_authorized",
                     "production_commit_performed"):
            self.assertFalse(v[name])

    def test_missing_archive_copy(self):
        self.archive["receipts"].pop()
        self.assertIn("invalid_archived_receipts", self.check()["errors"])

    def test_missing_historical_checkpoint(self):
        self.archive["receipts"][1]["history"]["entries"].pop()
        self.assertIn("missing_or_divergent_archive_history:1", self.check()["errors"])

    def test_altered_archived_consumed_row(self):
        self.archive["receipts"][0]["history"]["entries"][0]["rows"][0]["state"] = "ISSUED"
        self.assertIn("missing_or_divergent_archive_history:0", self.check()["errors"])

    def test_forged_archive_signature(self):
        self.archive["receipts"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertIn("invalid_archive_signature:0", self.check()["errors"])

    def test_duplicate_custodian(self):
        self.archive["receipts"][1]["custodian_id"] = "archive-a"
        self.assertIn("invalid_or_duplicate_receipt:1", self.check()["errors"])

    def test_wrong_custodian_key(self):
        self.trust["custodians"]["archive-b"]["public_key_hex"] = "f" * 64
        self.assertIn("custodian_trust_substitution", self.check()["errors"])

    def test_pin_with_replaced_head(self):
        self.pin["head_sha256"] = "a" * 64
        self.assertIn("independent_head_substitution", self.check()["errors"])

    def test_pin_with_replaced_history(self):
        self.pin["history_sha256"] = "b" * 64
        self.assertIn("independent_history_substitution", self.check()["errors"])

    def test_revoked_custodian(self):
        self.trust["custodians"]["archive-b"]["status"] = "revoked"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.assertIn("invalid_or_revoked_custodian:1", self.check()["errors"])

    def test_shared_organization(self):
        self.trust["custodians"]["archive-b"]["organization_id"] = "organization-archive-a"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.assertIn("overlapping_archive_custody:1", self.check()["errors"])

    def test_shared_domain(self):
        self.trust["custodians"]["archive-b"]["domain_id"] = "domain-archive-a"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.assertIn("overlapping_archive_custody:1", self.check()["errors"])

    def test_missing_original_checkpoint_cannot_be_fixed_by_archive(self):
        self.base.right["entries"].pop()
        self.assertTrue(any(x.startswith("v51:") for x in self.check()["errors"]))

    def test_different_valid_signed_branch_denied(self):
        self.base.right["entries"][1]["checkpoint"]["sequence"] = 4
        self.assertTrue(any(x.startswith("v51:") for x in self.check()["errors"]))

    def test_replay_signature_for_other_custodian(self):
        self.archive["receipts"][1]["signature_ed25519_hex"] = (
            self.archive["receipts"][0]["signature_ed25519_hex"])
        self.assertIn("invalid_archive_signature:1", self.check()["errors"])

    def test_pin_demands_more_receipts_than_present(self):
        self.pin["minimum_receipts"] = 3
        self.assertIn("insufficient_independent_history_receipts", self.check()["errors"])

    def test_rollback_minimum_checkpoint(self):
        self.pin["minimum_last_sequence"] = 4
        self.assertIn("archive_history_rollback", self.check()["errors"])

    def test_boolean_quorum_rejected(self):
        self.pin["minimum_receipts"] = True
        self.assertIn("invalid_external_archive_pin", self.check()["errors"])

    def test_unknown_custodian(self):
        self.archive["receipts"][0]["custodian_id"] = "not-registered"
        self.assertFalse(self.check()["archive_evidence_valid"])


if __name__ == "__main__":
    unittest.main()
