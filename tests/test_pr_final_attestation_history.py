"""GO-20 v29 complete signed final-report history and key rotation tests."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import ZERO, canonical_hash
from pr_final_attestation_history import (
    SCHEMA, PIN_SCHEMA, ROTATION_SCHEMA, verify_complete_history,
)
from test_pr_final_report_attestation import FinalAttestationTests


class InvalidFullHistoryTests(unittest.TestCase):
    def test_missing_inputs(self):
        out = verify_complete_history(None, None, None)
        self.assertFalse(out["history_valid"])
        self.assertEqual((out["decision"], out["authorization"]), ("HOLD", "DENY"))

    def test_invalid_trust(self):
        out = verify_complete_history(
            {"schema": SCHEMA, "entries": [{}], "rotations": []}, None, None)
        self.assertIn("invalid_external_custodian_trust", out["errors"])


class FullHistoryTests(unittest.TestCase):
    def setUp(self):
        fixture = FinalAttestationTests("test_genesis_attested_review_stays_hold")
        fixture.setUp()
        self.fixture = fixture
        self.trust = fixture.trust
        self.entries = [{"envelope": fixture.envelope,
                         "report": fixture.report, "inputs": fixture.inputs}]
        self.history = {"schema": SCHEMA, "entries": self.entries, "rotations": []}
        self.pin = self.repin()

    def repin(self):
        return {"schema": PIN_SCHEMA,
                "genesis_attestation_sha256": canonical_hash(self.entries[0]["envelope"]),
                "last_sequence": len(self.entries)-1,
                "last_attestation_sha256": canonical_hash(self.entries[-1]["envelope"])}

    def add_same_signer(self):
        previous = canonical_hash(self.entries[-1]["envelope"])
        self.entries.append({"envelope": self.fixture.sign(len(self.entries), previous),
                             "report": self.fixture.report,
                             "inputs": self.fixture.inputs})
        self.pin = self.repin()

    def add_rotated_signer(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        other_key = Ed25519PrivateKey.generate()
        self.trust["keys"]["new-custodian"] = {
            "public_key_hex": other_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex(),
            "status": "active", "role": "attestation_custodian",
        }
        previous_envelope = self.entries[-1]["envelope"]
        previous = canonical_hash(previous_envelope)
        new_envelope = self.fixture.sign(len(self.entries), previous)
        new_envelope["signer_key_id"] = "new-custodian"
        statement = new_envelope["statement"]
        new_envelope["signature_ed25519_hex"] = other_key.sign(
            bytes.fromhex(canonical_hash(statement))).hex()
        self.entries.append({"envelope": new_envelope, "report": self.fixture.report,
                             "inputs": self.fixture.inputs})
        data = {
            "transition_sequence": len(self.entries)-1,
            "previous_signer_id": "report-custodian",
            "new_signer_id": "new-custodian",
            "previous_attestation_sha256": previous,
            "new_attestation_sha256": canonical_hash(new_envelope),
        }
        stmt = {"schema": ROTATION_SCHEMA, **data}
        signature_digest = bytes.fromhex(canonical_hash(stmt))
        self.history["rotations"] = [{**data,
            "old_signature_ed25519_hex": self.fixture.key.sign(signature_digest).hex(),
            "new_signature_ed25519_hex": other_key.sign(signature_digest).hex()}]
        self.pin = self.repin()

    def check(self):
        return verify_complete_history(self.history, self.trust, self.pin)

    def test_genesis_remains_hold_deny(self):
        out = self.check()
        self.assertTrue(out["history_valid"], out["errors"])
        self.assertFalse(out["release_authorized"])
        self.assertFalse(out["merge_authorized"])
        self.assertEqual((out["decision"], out["authorization"]), ("HOLD", "DENY"))

    def test_three_complete_attestations(self):
        self.add_same_signer()
        self.add_same_signer()
        out = self.check()
        self.assertTrue(out["history_valid"], out["errors"])
        self.assertEqual(out["attestations_checked"], 3)

    def test_valid_double_signed_rotation(self):
        self.add_rotated_signer()
        out = self.check()
        self.assertTrue(out["history_valid"], out["errors"])
        self.assertEqual(out["custodian_rotations_verified"], 1)

    def test_rotation_without_cross_signatures_rejected(self):
        self.add_rotated_signer()
        self.history["rotations"] = []
        self.assertIn("unsigned_custodian_rotation:1", self.check()["errors"])

    def test_rotation_old_signature_tampered(self):
        self.add_rotated_signer()
        self.history["rotations"][0]["old_signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(x.startswith("rotation_signature:1:old:") for x in self.check()["errors"]))

    def test_rotation_new_signature_tampered(self):
        self.add_rotated_signer()
        self.history["rotations"][0]["new_signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(x.startswith("rotation_signature:1:new:") for x in self.check()["errors"]))

    def test_forged_rotation_binding_rejected(self):
        self.add_rotated_signer()
        self.history["rotations"][0]["previous_attestation_sha256"] = ZERO
        self.assertIn("rotation_binding_mismatch:1", self.check()["errors"])

    def test_forged_rotation_organization_same_key_rejected(self):
        self.add_rotated_signer()
        self.trust["keys"]["new-custodian"]["public_key_hex"] = self.trust["keys"]["report-custodian"]["public_key_hex"]
        self.assertFalse(self.check()["history_valid"])

    def test_missing_historical_middle_link(self):
        self.add_same_signer()
        self.add_same_signer()
        self.entries.pop(1)
        self.assertFalse(self.check()["history_valid"])

    def test_historical_signature_mutation_with_repin(self):
        self.add_same_signer()
        self.entries[0]["envelope"]["signature_ed25519_hex"] = "0" * 128
        self.pin = self.repin()
        self.assertFalse(self.check()["history_valid"])

    def test_external_last_anchor_mismatch(self):
        self.add_same_signer()
        self.pin["last_attestation_sha256"] = ZERO
        self.assertIn("independent_last_anchor_mismatch", self.check()["errors"])

    def test_external_genesis_anchor_mismatch(self):
        self.pin["genesis_attestation_sha256"] = ZERO
        self.assertIn("independent_genesis_anchor_mismatch", self.check()["errors"])

    def test_truncated_history_even_with_new_last_pin(self):
        self.add_same_signer()
        self.pin["last_sequence"] = 0
        self.assertIn("historical_truncation_or_sequence_rollback", self.check()["errors"])

    def test_revoked_old_signer_rejected(self):
        self.add_rotated_signer()
        self.trust["keys"]["report-custodian"]["status"] = "revoked"
        self.assertFalse(self.check()["history_valid"])

    def test_changed_history_report_denied(self):
        self.entries[0]["report"] = copy.deepcopy(self.entries[0]["report"])
        self.entries[0]["report"]["authorization"] = "ALLOW"
        self.assertFalse(self.check()["history_valid"])

    def test_malformed_intermediate_envelope_denied(self):
        self.add_same_signer()
        self.add_same_signer()
        self.entries[1]["envelope"] = None
        self.assertIn("malformed_historical_entry", self.check()["errors"])

    def test_replayed_genesis_in_middle(self):
        self.add_same_signer()
        self.entries[1]["envelope"] = copy.deepcopy(self.entries[0]["envelope"])
        self.assertIn("envelope:1:attestation_sequence_rollback_or_gap", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
