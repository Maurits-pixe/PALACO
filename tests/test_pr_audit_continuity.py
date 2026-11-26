"""GO-20 v18: independently witnessed cumulative checkpoint continuity tests."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pr_audit_continuity import verify_continuity, WITNESS_SCHEMA
from pr_audit_export import build_export
from pr_audit_integrity import canonical_hash
from pr_signed_audit_checkpoint import CHECKPOINT_SCHEMA, TRUST_SCHEMA


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("cryptography backend unavailable")
        self.key = Ed25519PrivateKey.generate()
        pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.trust = {"schema": TRUST_SCHEMA,
                      "keys": {"root": {"public_key_hex": pub, "status": "active"}}}
        self.rows = [
            {"id": 1, "operation": "INSERT", "actor_role": "go20test",
             "tenant_role": "go20_alpha", "entry_sha256": "a" * 64},
            {"id": 3, "operation": "INSERT", "actor_role": "go20test",
             "tenant_role": "go20_beta", "entry_sha256": "b" * 64},
            {"id": 7, "operation": "UPDATE", "actor_role": "go20test",
             "tenant_role": "go20_alpha", "entry_sha256": "c" * 64},
        ]
        self.previous = self.bundle(self.rows[:2], 11)
        self.current = self.bundle(self.rows, 12)
        self.witness = {
            "schema": WITNESS_SCHEMA, "revision": 11,
            "checkpoint_payload_sha256": canonical_hash(self.previous["checkpoint"]["payload"]),
        }

    def bundle(self, rows, revision):
        blob = build_export(copy.deepcopy(rows))
        m = blob["manifest"]
        payload = {
            "schema": CHECKPOINT_SCHEMA, "revision": revision,
            "repository": "Maurits-pixe/PALACO",
            "export_sha256": m["export_sha256"], "head_sha256": m["calculated_head_sha256"],
            "event_count": m["event_count"],
            "source_ids_sha256": canonical_hash(m["source_ids"]),
            "first_source_id": m["source_ids"][0], "last_source_id": m["source_ids"][-1],
        }
        statement = {"schema": "palaco.go20-audit-checkpoint-signature.v1",
                     "payload_sha256": canonical_hash(payload)}
        cp = {"payload": payload, "signer_key_id": "root",
              "signature_ed25519_hex": self.key.sign(bytes.fromhex(canonical_hash(statement))).hex()}
        return {"export": blob["export"], "manifest": m, "checkpoint": cp}

    def check(self):
        return verify_continuity(self.previous, self.current, self.trust, self.witness)

    def test_valid_append_stays_denied(self):
        v = self.check()
        self.assertTrue(v["continuity_valid"], v["errors"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_prior_independent_witness_changed(self):
        self.witness["checkpoint_payload_sha256"] = "0" * 64
        self.assertIn("independent_witness_hash_mismatch", self.check()["errors"])

    def test_witness_revision_changed(self):
        self.witness["revision"] = 10
        self.assertIn("independent_witness_revision_mismatch", self.check()["errors"])

    def test_missing_independent_witness(self):
        self.witness = None
        self.assertIn("invalid_independent_witness", self.check()["errors"])

    def test_replayed_checkpoint_rejected(self):
        self.current = copy.deepcopy(self.previous)
        self.assertFalse(self.check()["continuity_valid"])

    def test_checkpoint_revision_skip_rejected(self):
        self.current = self.bundle(self.rows, 13)
        self.assertIn("checkpoint_progression_mismatch", self.check()["errors"])

    def test_historical_event_loss(self):
        self.current = self.bundle([self.rows[0], self.rows[2]], 12)
        self.assertIn("historical_events_modified_or_missing", self.check()["errors"])

    def test_historical_payload_mutation(self):
        changed = copy.deepcopy(self.rows)
        changed[1]["tenant_role"] = "go20_alpha"
        self.current = self.bundle(changed, 12)
        self.assertIn("historical_events_modified_or_missing", self.check()["errors"])

    def test_historical_source_id_substitution(self):
        changed = copy.deepcopy(self.rows)
        changed[1]["id"] = 4
        self.current = self.bundle(changed, 12)
        self.assertIn("historical_source_ids_modified_or_missing", self.check()["errors"])

    def test_revoked_key(self):
        self.trust["keys"]["root"]["status"] = "revoked"
        self.assertFalse(self.check()["continuity_valid"])

    def test_invalid_current_signature(self):
        self.current["checkpoint"]["signature_ed25519_hex"] = "0" * 128
        self.assertFalse(self.check()["continuity_valid"])

    def test_missing_bundle(self):
        self.current = None
        self.assertIn("invalid_current_bundle", self.check()["errors"])

    def test_cross_repository_substitution(self):
        self.current["checkpoint"]["payload"]["repository"] = "bad/other"
        self.assertFalse(self.check()["continuity_valid"])


if __name__ == "__main__":
    unittest.main()
