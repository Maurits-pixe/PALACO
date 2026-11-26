"""GO-20 v62: historical signed succession custody and no-publication claims."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_head_succession_custody import (
    SCHEMA, PIN_SCHEMA, TRUST_SCHEMA, STATEMENT_SCHEMA, assess
)
from test_pr_reconstruction_head_succession import HeadSuccessionTests


class InvalidCustodyTests(unittest.TestCase):
    def test_missing_all_denies(self):
        v = assess(None, None, None, None)
        self.assertFalse(v["custody_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))


class SuccessionCustodyTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        base = HeadSuccessionTests("test_valid_history_remains_hold")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        self.sources = {
            "left": base.left, "left_pin": base.pin_left,
            "right": base.right, "right_pin": base.pin_right,
            "independent_head": base.head,
        }
        self.secrets = {mid: Ed25519PrivateKey.generate()
                        for mid in ("archive-a", "archive-b", "archive-c")}
        self.trust = {"schema": TRUST_SCHEMA, "members": {}}
        for mid, sk in self.secrets.items():
            self.trust["members"][mid] = {
                "public_key_hex": sk.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "organization_id": "org-" + mid,
                "domain_id": "domain-" + mid, "status": "active",
            }
        self.pin = {
            "schema": PIN_SCHEMA,
            "v61_sources_sha256": canonical_hash(self.sources),
            "history_sha256": canonical_hash(base.left),
            "copies_sha256": "0"*64,
            "custodian_trust_sha256": canonical_hash(self.trust),
            "minimum_round": 41,
            "minimum_receipts": 2,
        }
        self.copies = {"schema": SCHEMA, "rounds": []}
        for item in base.left["rounds"]:
            record = {"round": item["round"], "full_round_copy": copy.deepcopy(item),
                      "receipts": []}
            for mid in ("archive-a", "archive-b"):
                record["receipts"].append({
                    "custodian_id": mid,
                    "signature_ed25519_hex": self.sign(mid, item),
                })
            self.copies["rounds"].append(record)
        self.repin()

    def sign(self, mid, record):
        statement = {
            "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "round": record["round"],
            "round_sha256": canonical_hash(record),
            "previous_sha256": record["previous_sha256"],
            "history_sha256": self.pin["history_sha256"],
            "v61_sources_sha256": self.pin["v61_sources_sha256"],
            "custodian_trust_sha256": self.pin["custodian_trust_sha256"],
            "custodian_id": mid, "decision": "HOLD", "authorization": "DENY",
        }
        return self.secrets[mid].sign(bytes.fromhex(canonical_hash(statement))).hex()

    def repin(self):
        self.pin["copies_sha256"] = canonical_hash(self.copies)

    def check(self):
        return assess(self.sources, self.copies, self.trust, self.pin)

    def test_complete_archive_evidence_still_deny(self):
        r = self.check()
        self.assertTrue(r["custody_evidence_valid"], r["errors"])
        self.assertEqual((r["rounds_verified"], r["custodian_signatures_verified"]), (2, 4))
        for field in ("remote_publication_verified", "remote_storage_reachable",
                      "independent_custody_established", "history_restored",
                      "recovery_authorized", "merge_authorized",
                      "deployment_authorized", "production_commit_performed"):
            self.assertFalse(r[field])

    def test_missing_archived_round(self):
        self.copies["rounds"].pop()
        self.repin()
        self.assertIn("invalid_custody_bundle", self.check()["errors"])

    def test_missing_receipt(self):
        self.copies["rounds"][0]["receipts"].pop()
        self.repin()
        self.assertIn("missing_round_or_receipts:0", self.check()["errors"])

    def test_rewritten_full_round(self):
        self.copies["rounds"][1]["full_round_copy"]["round"] = 99
        self.repin()
        self.assertIn("mismatched_historical_round_copy:1", self.check()["errors"])

    def test_deleted_evidence_inside_archived_round(self):
        self.copies["rounds"][0]["full_round_copy"]["evidence"]["head_witnesses"]["witnesses"].pop()
        self.repin()
        self.assertIn("mismatched_historical_round_copy:0", self.check()["errors"])

    def test_forged_signature(self):
        self.copies["rounds"][0]["receipts"][0]["signature_ed25519_hex"] = "0"*128
        self.repin()
        self.assertIn("invalid_custody_signature:0:archive-a", self.check()["errors"])

    def test_replayed_signature_between_rounds(self):
        self.copies["rounds"][1]["receipts"][0]["signature_ed25519_hex"] = (
            self.copies["rounds"][0]["receipts"][0]["signature_ed25519_hex"])
        self.repin()
        self.assertIn("invalid_custody_signature:1:archive-a", self.check()["errors"])

    def test_duplicate_custodian(self):
        self.copies["rounds"][0]["receipts"][1] = copy.deepcopy(
            self.copies["rounds"][0]["receipts"][0])
        self.repin()
        self.assertIn("unknown_or_duplicate_custodian:0:1", self.check()["errors"])

    def test_unknown_custodian(self):
        self.copies["rounds"][0]["receipts"][0]["custodian_id"] = "unknown"
        self.repin()
        self.assertFalse(self.check()["custody_evidence_valid"])

    def test_revoked_custodian(self):
        self.trust["members"]["archive-b"]["status"] = "revoked"
        self.pin["custodian_trust_sha256"] = canonical_hash(self.trust)
        self.repin()
        self.assertIn("invalid_custodian:0:archive-b", self.check()["errors"])

    def test_overlapping_organization(self):
        self.trust["members"]["archive-b"]["organization_id"] = "org-archive-a"
        self.pin["custodian_trust_sha256"] = canonical_hash(self.trust)
        self.repin()
        self.assertIn("overlapping_custodian_domains:0:archive-b", self.check()["errors"])

    def test_overlapping_domain(self):
        self.trust["members"]["archive-b"]["domain_id"] = "domain-archive-a"
        self.pin["custodian_trust_sha256"] = canonical_hash(self.trust)
        self.repin()
        self.assertIn("overlapping_custodian_domains:0:archive-b", self.check()["errors"])

    def test_key_substitution_without_external_anchor(self):
        self.trust["members"]["archive-a"]["public_key_hex"] = "f"*64
        self.assertIn("independent_custody_anchor_mismatch", self.check()["errors"])

    def test_external_copy_pin_mutation(self):
        self.pin["copies_sha256"] = "a"*64
        self.assertIn("independent_custody_anchor_mismatch", self.check()["errors"])

    def test_external_history_anchor_mutation(self):
        self.pin["history_sha256"] = "a"*64
        self.assertIn("independent_custody_anchor_mismatch", self.check()["errors"])

    def test_minimum_round_rollback(self):
        self.pin["minimum_round"] = 42
        self.assertIn("missing_or_rollback_historical_publication", self.check()["errors"])

    def test_boolean_quorum_rejected(self):
        self.pin["minimum_receipts"] = True
        self.assertIn("invalid_external_custody_pin", self.check()["errors"])

    def test_raised_receipt_quorum(self):
        self.pin["minimum_receipts"] = 3
        self.repin()
        self.assertIn("missing_round_or_receipts:0", self.check()["errors"])

    def test_original_v61_chain_missing(self):
        self.sources["right"]["rounds"].pop()
        self.pin["v61_sources_sha256"] = canonical_hash(self.sources)
        self.repin()
        self.assertTrue(any(x.startswith("v61:") for x in self.check()["errors"]))

    def test_unpinned_copy_mutation_rejected_early(self):
        self.copies["rounds"][0]["receipts"][0]["signature_ed25519_hex"] = "0"*128
        self.assertIn("independent_custody_anchor_mismatch", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
