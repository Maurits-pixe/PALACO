"""GO-20 v19 witnessed audit fork / equivocation regression coverage."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pr_audit_witness_forks import (
    ATTESTATION_SCHEMA, SCHEMA, TRUST_SCHEMA, examine_witnesses,
)
from pr_audit_export import build_export
from pr_audit_integrity import canonical_hash
from pr_signed_audit_checkpoint import CHECKPOINT_SCHEMA, TRUST_SCHEMA as AUDIT_TRUST


class InvalidWitnessInputTests(unittest.TestCase):
    def test_missing_evidence_fails_closed(self):
        v = examine_witnesses(None, None, None, 2)
        self.assertIn("invalid_witness_evidence", v["errors"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_invalid_quorum_fails_closed(self):
        v = examine_witnesses({}, None, None, 2, 1)
        self.assertIn("invalid_quorum", v["errors"])

    def test_missing_registry_fails_closed(self):
        evidence = {"schema": SCHEMA, "bundles": [{}], "attestations": [{}]}
        self.assertIn("invalid_witness_trust",
                      examine_witnesses(evidence, None, None, 2)["errors"])


class WitnessForkTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("cryptography backend not available")
        self.audit_key = Ed25519PrivateKey.generate()
        self.witness_private = {
            wid: Ed25519PrivateKey.generate() for wid in ("w1", "w2", "w3", "w4")
        }
        def public(key):
            return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.audit_trust = {"schema": AUDIT_TRUST, "keys": {
            "audit": {"public_key_hex": public(self.audit_key), "status": "active"}
        }}
        self.witness_trust = {"schema": TRUST_SCHEMA, "keys": {
            wid: {"public_key_hex": public(key), "status": "active"}
            for wid, key in self.witness_private.items()
        }}
        self.revision = 42
        self.base_rows = [
            {"id": 1, "operation": "INSERT", "actor_role": "synthetic",
             "tenant_role": "go20_alpha", "entry_sha256": "a" * 64},
        ]
        self.bundle_a = self.bundle(self.base_rows)
        fork_rows = copy.deepcopy(self.base_rows)
        fork_rows[0]["tenant_role"] = "go20_beta"
        self.bundle_b = self.bundle(fork_rows)
        self.sha_a = canonical_hash(self.bundle_a["checkpoint"]["payload"])
        self.sha_b = canonical_hash(self.bundle_b["checkpoint"]["payload"])

    def bundle(self, rows):
        blob = build_export(copy.deepcopy(rows))
        manifest = blob["manifest"]
        payload = {
            "schema": CHECKPOINT_SCHEMA, "revision": self.revision,
            "repository": "Maurits-pixe/PALACO",
            "export_sha256": manifest["export_sha256"],
            "head_sha256": manifest["calculated_head_sha256"],
            "event_count": manifest["event_count"],
            "source_ids_sha256": canonical_hash(manifest["source_ids"]),
            "first_source_id": manifest["source_ids"][0],
            "last_source_id": manifest["source_ids"][-1],
        }
        statement = {"schema": "palaco.go20-audit-checkpoint-signature.v1",
                     "payload_sha256": canonical_hash(payload)}
        signature = self.audit_key.sign(bytes.fromhex(canonical_hash(statement))).hex()
        return {"export": blob["export"], "manifest": manifest,
                "checkpoint": {"payload": payload, "signer_key_id": "audit",
                               "signature_ed25519_hex": signature}}

    def attestation(self, wid, h):
        statement = {
            "schema": ATTESTATION_SCHEMA, "witness_id": wid,
            "revision": self.revision, "checkpoint_payload_sha256": h,
        }
        return {"witness_id": wid, "revision": self.revision,
                "checkpoint_payload_sha256": h,
                "signature_ed25519_hex": self.witness_private[wid].sign(
                    bytes.fromhex(canonical_hash(statement))).hex()}

    def review(self, bundles=None, endorsements=None):
        evidence = {"schema": SCHEMA,
                    "bundles": self.bundle_a if bundles is None else bundles,
                    "attestations": endorsements or []}
        if bundles is None:
            evidence["bundles"] = [self.bundle_a]
        return examine_witnesses(evidence, self.audit_trust,
                                 self.witness_trust, self.revision)

    def test_two_independent_witnesses_valid_still_denied(self):
        v = self.review(endorsements=[self.attestation("w1", self.sha_a),
                                       self.attestation("w2", self.sha_a)])
        self.assertTrue(v["evidence_valid"], v["errors"])
        self.assertFalse(v["fork_detected"])
        self.assertEqual(v["independently_endorsed_checkpoint_count"], 1)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_two_signed_competing_histories_detected(self):
        v = self.review(
            bundles=[self.bundle_a, self.bundle_b],
            endorsements=[self.attestation("w1", self.sha_a),
                          self.attestation("w2", self.sha_a),
                          self.attestation("w3", self.sha_b),
                          self.attestation("w4", self.sha_b)])
        self.assertTrue(v["fork_detected"])
        self.assertIn("signed_checkpoint_fork_detected", v["errors"])
        self.assertEqual(v["independently_endorsed_checkpoint_count"], 2)
        self.assertEqual(len(v["conflicting_checkpoint_sha256"]), 2)

    def test_single_witness_not_quorum(self):
        v = self.review(endorsements=[self.attestation("w1", self.sha_a)])
        self.assertIn("insufficient_independent_witnesses", v["errors"])

    def test_unknown_witness(self):
        att = self.attestation("w1", self.sha_a)
        att["witness_id"] = "outsider"
        self.assertIn("unknown_witness:0", self.review(endorsements=[att])["errors"])

    def test_revoked_witness(self):
        self.witness_trust["keys"]["w1"]["status"] = "revoked"
        self.assertIn("revoked_witness:0", self.review(
            endorsements=[self.attestation("w1", self.sha_a)])["errors"])

    def test_duplicate_witness_not_double_counted(self):
        att = self.attestation("w1", self.sha_a)
        v = self.review(endorsements=[att, copy.deepcopy(att)])
        self.assertIn("duplicate_witness_attestation:1", v["errors"])
        self.assertEqual(v["independently_endorsed_checkpoint_count"], 0)

    def test_witness_equivocation_detected(self):
        v = self.review(
            bundles=[self.bundle_a, self.bundle_b],
            endorsements=[self.attestation("w1", self.sha_a),
                          self.attestation("w1", self.sha_b)])
        self.assertIn("witness_equivocation:w1", v["errors"])
        self.assertTrue(v["fork_detected"])

    def test_tampered_witness_signature(self):
        att = self.attestation("w1", self.sha_a)
        att["signature_ed25519_hex"] = "0" * 128
        v = self.review(endorsements=[att])
        self.assertTrue(any(x.startswith("witness_signature:0:") for x in v["errors"]))

    def test_unmatched_checkpoint_digest(self):
        att = self.attestation("w1", self.sha_a)
        att["checkpoint_payload_sha256"] = "0" * 64
        self.assertIn("unmatched_checkpoint:0", self.review(endorsements=[att])["errors"])

    def test_different_revision_rejected(self):
        att = self.attestation("w1", self.sha_a)
        att["revision"] = 43
        self.assertIn("attestation_revision_mismatch:0", self.review(endorsements=[att])["errors"])

    def test_checkpoint_signer_revoked(self):
        self.audit_trust["keys"]["audit"]["status"] = "revoked"
        v = self.review(endorsements=[self.attestation("w1", self.sha_a)])
        self.assertIn("bundle:0:revoked_checkpoint_signer", v["errors"])

    def test_source_history_tampered(self):
        bundle = copy.deepcopy(self.bundle_a)
        bundle["export"]["events"][0]["tenant_role"] = "go20_beta"
        v = self.review(bundles=[bundle],
                        endorsements=[self.attestation("w1", self.sha_a)])
        self.assertIn("bundle:0:signed_export_digest_mismatch", v["errors"])

    def test_duplicate_checkpoint_bundle_rejected(self):
        v = self.review(
            bundles=[self.bundle_a, copy.deepcopy(self.bundle_a)],
            endorsements=[self.attestation("w1", self.sha_a),
                          self.attestation("w2", self.sha_a)])
        self.assertIn("duplicate_checkpoint_bundle", v["errors"])


if __name__ == "__main__":
    unittest.main()
