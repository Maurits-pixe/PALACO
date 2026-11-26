"""GO-20 v50: signed snapshot anchors, SQLite rollback and integrity tests."""
import copy
import shutil
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_challenge_ledger_checkpoint import SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, snapshot, assess
from test_pr_challenge_lifecycle_ledger import LifecycleTests


class LedgerCheckpointTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        source = LifecycleTests("test_issue_and_verified_consume")
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.source = source
        source.issue()
        source.consume()
        self.rows = snapshot(source.path)
        self.secret = Ed25519PrivateKey.generate()
        public = self.secret.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.checkpoint = {
            "schema": SCHEMA, "repository": "Maurits-pixe/PALACO",
            "sequence": 2, "rows_sha256": canonical_hash(self.rows),
            "row_count": len(self.rows), "minimum_consumed": 1,
            "previous_checkpoint_sha256": "0" * 64,
        }
        self.pin = {
            "schema": PIN_SCHEMA, "key_id": "external-checkpoint-keeper",
            "public_key_hex": public,
            "checkpoint_sha256": canonical_hash(self.checkpoint),
            "minimum_sequence": 2, "minimum_rows": 1,
            "minimum_consumed": 1,
        }
        self.signature = {"key_id": "external-checkpoint-keeper",
                          "signature_ed25519_hex": self.sign()}

    def sign(self):
        statement = {
            "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "checkpoint_sha256": canonical_hash(self.checkpoint),
            "key_id": self.pin["key_id"],
            "decision": "HOLD", "authorization": "DENY",
        }
        return self.secret.sign(bytes.fromhex(canonical_hash(statement))).hex()

    def check(self):
        return assess(self.rows, self.checkpoint, self.pin, self.signature)

    def test_verified_signed_snapshot_remains_hold(self):
        result = self.check()
        self.assertTrue(result["ledger_checkpoint_valid"], result["errors"])
        self.assertEqual(result["rows_verified"], 1)
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))
        for field in ("database_restored", "rollback_recovery_authorized",
                      "challenge_reopened", "failover_authorized",
                      "merge_authorized", "deployment_authorized",
                      "production_commit_performed"):
            self.assertFalse(result[field])

    def test_edited_consumed_state_detected(self):
        self.rows[0]["state"] = "ISSUED"
        self.rows[0]["consumed_at"] = None
        self.assertIn("ledger_snapshot_divergence_or_rollback", self.check()["errors"])

    def test_missing_consumed_row_detected(self):
        self.rows.clear()
        self.assertIn("ledger_snapshot_divergence_or_rollback", self.check()["errors"])

    def test_unpinned_checkpoint_rejected(self):
        self.checkpoint["sequence"] = 3
        self.assertIn("independent_checkpoint_anchor_mismatch", self.check()["errors"])

    def test_forged_signature_detected(self):
        self.signature["signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(x.startswith("checkpoint_signature_invalid:")
                            for x in self.check()["errors"]))

    def test_mismatched_signer_identity(self):
        self.signature["key_id"] = "attacker"
        self.assertIn("invalid_checkpoint_signature", self.check()["errors"])

    def test_replaced_trust_key(self):
        self.pin["public_key_hex"] = "a" * 64
        self.assertFalse(self.check()["ledger_checkpoint_valid"])

    def test_unsigned_rollback_fails(self):
        self.checkpoint["minimum_consumed"] = 0
        self.assertFalse(self.check()["ledger_checkpoint_valid"])

    def test_resigned_downgrade_below_pinned_floor(self):
        self.checkpoint["minimum_consumed"] = 0
        self.pin["checkpoint_sha256"] = canonical_hash(self.checkpoint)
        self.signature["signature_ed25519_hex"] = self.sign()
        self.assertIn("retention_floor_rollback", self.check()["errors"])

    def test_replay_older_sequence_rejected(self):
        self.checkpoint["sequence"] = 1
        self.pin["checkpoint_sha256"] = canonical_hash(self.checkpoint)
        self.signature["signature_ed25519_hex"] = self.sign()
        self.assertIn("checkpoint_sequence_rollback", self.check()["errors"])

    def test_duplicate_nonce_rejected(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        self.assertIn("duplicate_nonces", self.check()["errors"])

    def test_boolean_pinned_minimum_rejected(self):
        self.pin["minimum_rows"] = True
        self.assertIn("invalid_independent_checkpoint_pin", self.check()["errors"])

    def test_missing_database_rejected(self):
        with self.assertRaises(ValueError):
            snapshot(self.source.path.parent / "not-there.db")

    def test_read_only_snapshot_does_not_mutate_rows(self):
        before = self.source.ledger.inspect(self.source.challenge["nonce_sha256"])
        self.assertEqual(snapshot(self.source.path), self.rows)
        self.assertEqual(self.source.ledger.inspect(self.source.challenge["nonce_sha256"]), before)

    def test_sqlite_rollback_via_delete_detected(self):
        import sqlite3
        with sqlite3.connect(self.source.path) as db:
            db.execute("DELETE FROM challenge_ledger")
        self.assertIn("ledger_snapshot_divergence_or_rollback",
                      assess(snapshot(self.source.path), self.checkpoint,
                             self.pin, self.signature)["errors"])

    def test_table_removed_detected(self):
        import sqlite3
        with sqlite3.connect(self.source.path) as db:
            db.execute("DROP TABLE challenge_ledger")
        with self.assertRaises(ValueError):
            snapshot(self.source.path)

    def test_malformed_row_shape_rejected(self):
        self.rows[0]["unexpected"] = "x"
        self.assertIn("invalid_rows", self.check()["errors"])

    def test_challenge_row_cannot_be_reopened(self):
        self.rows[0]["state"] = "ISSUED"
        self.rows[0]["consumed_at"] = None
        self.assertFalse(self.check()["challenge_reopened"])
        self.assertFalse(self.check()["ledger_checkpoint_valid"])


if __name__ == "__main__":
    unittest.main()
