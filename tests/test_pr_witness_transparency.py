"""GO-20 v20: signed publication history, fork, and pinning regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pr_audit_integrity import ZERO, canonical_hash
from pr_audit_witness_forks import TRUST_SCHEMA
from pr_witness_transparency import (
    ENTRY_SCHEMA, PIN_SCHEMA, SCHEMA, verify_transparency
)


class TransparencyInputTests(unittest.TestCase):
    def test_no_logs_rejected(self):
        v = verify_transparency(None, None, None, 7)
        self.assertIn("invalid_logbook", v["errors"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_no_trust_rejected(self):
        v = verify_transparency(
            {"schema": SCHEMA, "logs": [{"witness_id": "a"}, {"witness_id": "b"}]},
            None, None, 7)
        self.assertIn("invalid_witness_trust", v["errors"])

    def test_no_external_pins_rejected(self):
        v = verify_transparency(
            {"schema": SCHEMA, "logs": [{"witness_id": "a"}, {"witness_id": "b"}]},
            {"schema": TRUST_SCHEMA, "keys": {}}, None, 7)
        self.assertIn("invalid_independent_pins", v["errors"])


class TransparencyTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("optional cryptography backend absent")
        self.private = {wid: Ed25519PrivateKey.generate() for wid in ("w1", "w2")}
        self.trust = {"schema": TRUST_SCHEMA, "keys": {
            wid: {"public_key_hex": key.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw).hex(), "status": "active"}
            for wid, key in self.private.items()
        }}
        self.start = 21
        self.logs = {"schema": SCHEMA, "logs": [
            self.log("w1", ["a" * 64, "b" * 64]),
            self.log("w2", ["a" * 64, "b" * 64]),
        ]}
        self.pins = self.pinned()

    def log(self, wid, digests):
        entries = []
        previous = ZERO
        for index, h in enumerate(digests, 1):
            statement = {
                "schema": ENTRY_SCHEMA, "witness_id": wid, "sequence": index,
                "revision": self.start + index - 1, "checkpoint_payload_sha256": h,
                "previous_entry_sha256": previous,
            }
            item = {
                "sequence": index, "revision": statement["revision"],
                "checkpoint_payload_sha256": h,
                "previous_entry_sha256": previous,
                "entry_sha256": canonical_hash(statement),
                "signature_ed25519_hex": self.private[wid].sign(
                    bytes.fromhex(canonical_hash(statement))).hex(),
            }
            entries.append(item)
            previous = item["entry_sha256"]
        return {"witness_id": wid, "entries": entries}

    def pinned(self):
        return {"schema": PIN_SCHEMA, "witnesses": {
            log["witness_id"]: {
                "last_sequence": len(log["entries"]),
                "head_sha256": log["entries"][-1]["entry_sha256"],
            } for log in self.logs["logs"]
        }}

    def check(self):
        return verify_transparency(self.logs, self.trust, self.pins, self.start)

    def test_identical_signed_histories_stay_hold(self):
        v = self.check()
        self.assertTrue(v["history_valid"], v["errors"])
        self.assertFalse(v["fork_detected"])
        self.assertEqual(v["verified_entry_count"], 4)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_conflicting_signed_publications_detected(self):
        self.logs["logs"][1] = self.log("w2", ["a" * 64, "c" * 64])
        self.pins = self.pinned()
        v = self.check()
        self.assertIn("conflicting_signed_publications", v["errors"])
        self.assertTrue(v["fork_detected"])
        self.assertEqual(v["fork_revisions"], [22])

    def test_changed_log_without_changed_external_pin(self):
        self.logs["logs"][1] = self.log("w2", ["a" * 64, "c" * 64])
        self.assertIn("independent_head_mismatch:w2", self.check()["errors"])

    def test_truncated_history_detected(self):
        self.logs["logs"][0]["entries"].pop()
        self.assertIn("independent_head_mismatch:w1", self.check()["errors"])

    def test_missing_middle_entry_detected(self):
        self.logs["logs"][0]["entries"] = [self.logs["logs"][0]["entries"][1]]
        self.assertIn("sequence_gap:w1:1", self.check()["errors"])

    def test_reordered_history_detected(self):
        self.logs["logs"][0]["entries"].reverse()
        self.assertFalse(self.check()["history_valid"])

    def test_modified_record_rejected(self):
        self.logs["logs"][0]["entries"][0]["checkpoint_payload_sha256"] = "c" * 64
        self.assertIn("entry_hash_mismatch:w1:1", self.check()["errors"])

    def test_signature_tamper_rejected(self):
        self.logs["logs"][0]["entries"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(x.startswith("signature:w1:1:") for x in self.check()["errors"]))

    def test_revoked_witness_rejected(self):
        self.trust["keys"]["w1"]["status"] = "revoked"
        self.assertIn("untrusted_or_revoked_witness:w1", self.check()["errors"])

    def test_same_witness_multiple_logs_rejected(self):
        self.logs["logs"][1]["witness_id"] = "w1"
        self.assertIn("duplicate_or_invalid_witness_log", self.check()["errors"])

    def test_missing_witness_pin_rejected(self):
        del self.pins["witnesses"]["w1"]
        self.assertIn("independent_pin_coverage_mismatch", self.check()["errors"])

    def test_revision_replay_rejected(self):
        self.logs["logs"][1]["entries"][1]["revision"] = self.start
        self.assertIn("revision_gap:w2:2", self.check()["errors"])

    def test_unequal_publication_horizons_rejected(self):
        self.logs["logs"][0] = self.log("w1", ["a" * 64])
        self.pins = self.pinned()
        self.assertIn("unequal_publication_horizons", self.check()["errors"])

    def test_wrong_start_revision_rejected(self):
        v = verify_transparency(self.logs, self.trust, self.pins, self.start + 1)
        self.assertIn("revision_gap:w1:1", v["errors"])


if __name__ == "__main__":
    unittest.main()
