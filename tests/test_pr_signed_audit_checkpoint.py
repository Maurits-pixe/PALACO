"""GO-20 v17: signed checkpoint trust, revocation and completeness tests."""
import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("pr_signed_audit_checkpoint", ROOT / "scripts" / "pr_signed_audit_checkpoint.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from pr_audit_export import build_export
from pr_audit_integrity import canonical_hash


class SignedCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.bundle = build_export([
            {"id": 1, "operation": "INSERT", "actor_role": "go20test",
             "tenant_role": "go20_alpha", "entry_sha256": "a" * 64},
            {"id": 4, "operation": "INSERT", "actor_role": "go20test",
             "tenant_role": "go20_beta", "entry_sha256": "b" * 64},
        ])
        manifest = self.bundle["manifest"]
        self.checkpoint = {
            "payload": {
                "schema": module.CHECKPOINT_SCHEMA, "revision": 7,
                "repository": "Maurits-pixe/PALACO",
                "export_sha256": manifest["export_sha256"],
                "head_sha256": manifest["calculated_head_sha256"],
                "event_count": manifest["event_count"],
                "source_ids_sha256": canonical_hash(manifest["source_ids"]),
                "first_source_id": 1, "last_source_id": 4,
            },
            "signer_key_id": "review-root",
            "signature_ed25519_hex": "0" * 128,
        }
        self.trust = {"schema": module.TRUST_SCHEMA, "keys": {
            "review-root": {"public_key_hex": "a" * 64, "status": "active"},
        }}

    def check(self, minimum_revision=7):
        return module.verify_checkpoint(self.bundle["export"], self.bundle["manifest"],
                                        self.checkpoint, self.trust, minimum_revision)

    def test_revoked_signer_fails_closed(self):
        self.trust["keys"]["review-root"]["status"] = "revoked"
        result = self.check()
        self.assertIn("revoked_checkpoint_signer", result["errors"])
        self.assertEqual(result["authorization"], "DENY")

    def test_unknown_signer_fails_closed(self):
        self.checkpoint["signer_key_id"] = "not-trusted"
        self.assertIn("untrusted_checkpoint_signer", self.check()["errors"])

    def test_missing_trust_registry(self):
        self.trust = None
        self.assertIn("invalid_external_trust_registry", self.check()["errors"])

    def test_trust_registry_bad_key(self):
        self.trust["keys"]["review-root"]["public_key_hex"] = "not-a-key"
        self.assertIn("invalid_external_key_record", self.check()["errors"])

    def test_stale_revision_rejected(self):
        self.assertIn("checkpoint_revision_rollback", self.check(8)["errors"])

    def test_revised_manifest_source_ids_rejected(self):
        self.bundle["manifest"]["source_ids"] = [1, 5]
        self.assertIn("signed_source_completeness_mismatch", self.check()["errors"])

    def test_missing_event_rejected(self):
        self.bundle["export"]["events"].pop()
        self.assertIn("signed_event_count_mismatch", self.check()["errors"])

    def test_forged_export_rejected(self):
        self.bundle["export"]["events"][0]["tenant_role"] = "forged"
        self.assertIn("signed_export_digest_mismatch", self.check()["errors"])

    def test_repository_substitution_rejected(self):
        self.checkpoint["payload"]["repository"] = "example/other"
        self.assertIn("checkpoint_repository_mismatch", self.check()["errors"])

    def test_invalid_signature_encoding(self):
        self.checkpoint["signature_ed25519_hex"] = "bad"
        self.assertIn("invalid_signature_encoding", self.check()["errors"])

    def test_manifest_mismatched_hash(self):
        self.bundle["manifest"]["export_sha256"] = "0" * 64
        self.assertIn("signed_export_manifest_mismatch", self.check()["errors"])

    def test_duplicate_json_key(self):
        import json
        with self.assertRaises(ValueError):
            json.loads('{"payload":1,"payload":2}', object_pairs_hook=module.unique_pairs)

    def test_cryptographic_positive_and_tampered_signature(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("optional cryptography backend not installed")
        key = Ed25519PrivateKey.generate()
        self.trust["keys"]["review-root"]["public_key_hex"] = key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw).hex()
        statement = {"schema": "palaco.go20-audit-checkpoint-signature.v1",
                     "payload_sha256": canonical_hash(self.checkpoint["payload"])}
        self.checkpoint["signature_ed25519_hex"] = key.sign(
            bytes.fromhex(canonical_hash(statement))).hex()
        result = self.check()
        self.assertTrue(result["checkpoint_valid"], result["errors"])
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))
        self.checkpoint["payload"]["revision"] = 8
        self.assertFalse(self.check()["checkpoint_valid"])
        self.checkpoint["payload"]["revision"] = 7
        self.trust["keys"]["review-root"]["status"] = "revoked"
        self.assertFalse(self.check()["checkpoint_valid"])


if __name__ == "__main__":
    unittest.main()
