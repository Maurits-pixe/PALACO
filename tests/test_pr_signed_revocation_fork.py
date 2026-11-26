"""GO-20 v44: independently signed revocations and two-view historical forks."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_signed_revocation_fork import SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, check
from test_pr_fencing_quorum_history import HistoricalQuorumTests


class InvalidForkInputs(unittest.TestCase):
    def test_missing_sources_fail_closed(self):
        v = check(None, None, None, None, None, None, None)
        self.assertFalse(v["historical_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["failover_authorized"])

    def test_nonjson_data_rejected(self):
        v = check({"invalid": {1, 2}}, None, None, None, None, None, None)
        self.assertFalse(v["historical_evidence_valid"])


class ForkProofTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        baseline = HistoricalQuorumTests("test_two_epoch_quorum_history")
        baseline.setUp()
        self.baseline = baseline
        self.left = baseline.history
        self.left_pin = baseline.pin
        self.right = copy.deepcopy(self.left)
        self.right_pin = copy.deepcopy(self.left_pin)
        self.revocations = baseline.revocations
        self.secret = Ed25519PrivateKey.generate()
        key = self.secret.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.pin = {
            "schema": PIN_SCHEMA,
            "trusted_key_id": "external-revocation-keeper",
            "trusted_public_key_hex": key,
            "revocations_sha256": canonical_hash(self.revocations),
            "history_sha256": canonical_hash(self.left),
            "minimum_epoch": 9,
        }
        self.signed = {"schema": SCHEMA, "key_id": "external-revocation-keeper",
                       "signature_ed25519_hex": self.make_signature()}

    def make_signature(self):
        statement = {
            "schema": STATEMENT_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "revocations_sha256": self.pin["revocations_sha256"],
            "minimum_epoch": self.pin["minimum_epoch"],
            "history_sha256": self.pin["history_sha256"],
            "decision": "HOLD",
            "authorization": "DENY",
        }
        return self.secret.sign(bytes.fromhex(canonical_hash(statement))).hex()

    def check(self):
        return check(self.left, self.left_pin, self.right, self.right_pin,
                     self.revocations, self.signed, self.pin)

    def fork_with_valid_alternative_votes(self):
        # Both histories pass v43 independently, but the second offers
        # a different valid third Ed25519 quorum signature.
        self.right["snapshots"][1]["signed_votes"]["votes"].append(
            self.baseline.base.sign("observer-two"))
        self.right_pin["last_snapshot_sha256"] = canonical_hash(self.right["snapshots"][-1])
        self.right_pin["history_sha256"] = canonical_hash(self.right)

    def test_equivalent_histories_still_denied_authority(self):
        v = self.check()
        self.assertTrue(v["historical_evidence_valid"], v["errors"])
        self.assertEqual(v["histories_verified"], 2)
        self.assertEqual(v["epochs_verified"], 2)
        for name in ("failover_authorized", "promotion_performed",
                     "fence_performed", "release_authorized",
                     "merge_authorized", "deployment_authorized",
                     "production_commit_performed"):
            self.assertFalse(v[name])

    def test_detects_two_cryptographically_valid_forks(self):
        self.fork_with_valid_alternative_votes()
        v = self.check()
        self.assertIn("historical_fork_detected", v["errors"])
        self.assertIn("right_history_external_anchor_mismatch", v["errors"])

    def test_forged_registry_signature(self):
        self.signed["signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(e.startswith("invalid_revocation_signature")
                            for e in self.check()["errors"]))

    def test_signature_wrong_public_key(self):
        self.pin["trusted_public_key_hex"] = "a" * 64
        self.assertFalse(self.check()["historical_evidence_valid"])

    def test_revoked_registry_not_independently_pinned(self):
        self.revocations["entries"].append({
            "public_key_hex": "a" * 64, "effective_epoch": 9})
        self.assertIn("independent_revocation_mismatch", self.check()["errors"])

    def test_attacker_resigns_new_registry_without_history_pin(self):
        self.revocations["entries"].append({
            "public_key_hex": "a" * 64, "effective_epoch": 9})
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.signed["signature_ed25519_hex"] = self.make_signature()
        self.assertFalse(self.check()["historical_evidence_valid"])

    def test_old_signature_cannot_replay_new_minimum_epoch(self):
        self.pin["minimum_epoch"] = 10
        self.assertFalse(self.check()["historical_evidence_valid"])

    def test_external_history_anchor_tampered(self):
        self.pin["history_sha256"] = "b" * 64
        self.assertFalse(self.check()["historical_evidence_valid"])

    def test_changed_left_history_rejected(self):
        self.left["snapshots"][0]["handoff_pin"]["minimum_rows"] = 1
        self.assertFalse(self.check()["historical_evidence_valid"])

    def test_changed_right_history_rejected(self):
        self.right["snapshots"][0]["handoff_pin"]["minimum_rows"] = 1
        self.assertFalse(self.check()["historical_evidence_valid"])

    def test_truncated_right_history_rejected(self):
        self.right["snapshots"].pop()
        self.assertFalse(self.check()["historical_evidence_valid"])

    def test_wrong_signer_id(self):
        self.signed["key_id"] = "attacker"
        self.assertIn("revocation_signer_identity_mismatch", self.check()["errors"])

    def test_boolean_pin_epoch_rejected(self):
        self.pin["minimum_epoch"] = True
        self.assertIn("invalid_independent_revocation_pin", self.check()["errors"])

    def test_invalid_signature_encoding_rejected(self):
        self.signed["signature_ed25519_hex"] = "bad"
        self.assertIn("invalid_signed_revocation_register", self.check()["errors"])

    def test_missing_pin_field_rejected(self):
        self.pin.pop("trusted_public_key_hex")
        self.assertIn("invalid_independent_revocation_pin", self.check()["errors"])

    def test_resigned_fork_still_rejected(self):
        self.fork_with_valid_alternative_votes()
        # Even a newly issued signature over the old expected head does
        # not legitimize the alternative history.
        self.signed["signature_ed25519_hex"] = self.make_signature()
        self.assertIn("historical_fork_detected", self.check()["errors"])

    def test_epoch_rollback_denied(self):
        self.pin["minimum_epoch"] = 10
        self.signed["signature_ed25519_hex"] = self.make_signature()
        self.assertIn("history_epoch_rollback", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
