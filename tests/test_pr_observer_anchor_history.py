"""GO-20 v32: historical observer continuity and revocation regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_observer_anchor_history import (
    SCHEMA, PIN_SCHEMA, REVOCATION_SCHEMA, ROTATION_SCHEMA,
    verify_observer_history,
)
from test_pr_observer_anchor_custody import ObserverCustodyTests


class InvalidHistoricalObserverTests(unittest.TestCase):
    def test_missing_inputs_fail_closed(self):
        v = verify_observer_history(None, None, None)
        self.assertFalse(v["history_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_invalid_revocation_register(self):
        v = verify_observer_history(
            {"schema": SCHEMA, "epochs": [{}, {}], "rotations": []},
            {"schema": PIN_SCHEMA}, None)
        self.assertIn("invalid_independent_history_pin", v["errors"])


class HistoricalObserverTests(unittest.TestCase):
    def setUp(self):
        base = ObserverCustodyTests("test_two_valid_independent_views_remain_hold_deny")
        base.setUp()
        self.base = base
        self.private = copy.copy(base.private)
        self.first = {
            "epoch": 7, "views": copy.deepcopy(base.views),
            "history_pins": copy.deepcopy(base.history_pins),
            "signed_anchors": copy.deepcopy(base.signed),
            "observer_trust": copy.deepcopy(base.trust),
            "independent_heads": copy.deepcopy(base.heads),
        }
        self.second = copy.deepcopy(self.first)
        self.second["epoch"] = 8
        for n, item in enumerate(self.second["signed_anchors"]["anchors"]):
            vid = item["view_id"]
            statement = item["statement"]
            statement["epoch"] = 8
            item["signature_ed25519_hex"] = self.private[vid].sign(
                bytes.fromhex(canonical_hash(statement))).hex()
            self.second["independent_heads"]["heads"][vid] = {
                "minimum_epoch": 8, "receipt_sha256": canonical_hash(item)}
        self.history = {"schema": SCHEMA, "epochs": [self.first, self.second],
                        "rotations": []}
        self.revocations = {"schema": REVOCATION_SCHEMA, "entries": []}
        self.pin = self.repin()

    def repin(self):
        return {
            "schema": PIN_SCHEMA,
            "first_epoch": 7, "last_epoch": 8,
            "first_snapshot_sha256": canonical_hash(self.first),
            "last_snapshot_sha256": canonical_hash(self.second),
            "revocation_register_sha256": canonical_hash(self.revocations),
        }

    def check(self):
        return verify_observer_history(self.history, self.pin, self.revocations)

    def rotate_observer_b(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        vid = "observer-b"
        new_private = Ed25519PrivateKey.generate()
        old_private = self.private[vid]
        old_anchor = next(a for a in self.first["signed_anchors"]["anchors"]
                          if a["view_id"] == vid)
        old_pub = self.first["observer_trust"]["observers"][vid]["public_key_hex"]
        new_pub = new_private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.second["observer_trust"]["observers"][vid]["public_key_hex"] = new_pub
        new_anchor = next(a for a in self.second["signed_anchors"]["anchors"]
                          if a["view_id"] == vid)
        new_anchor["signature_ed25519_hex"] = new_private.sign(
            bytes.fromhex(canonical_hash(new_anchor["statement"]))).hex()
        self.second["independent_heads"]["heads"][vid]["receipt_sha256"] = canonical_hash(new_anchor)
        data = {
            "epoch": 8, "view_id": vid,
            "old_public_key_hex": old_pub,
            "new_public_key_hex": new_pub,
            "old_anchor_sha256": canonical_hash(old_anchor),
            "new_anchor_sha256": canonical_hash(new_anchor),
        }
        msg = bytes.fromhex(canonical_hash({"schema": ROTATION_SCHEMA, **data}))
        self.history["rotations"] = [{**data,
            "old_signature_ed25519_hex": old_private.sign(msg).hex(),
            "new_signature_ed25519_hex": new_private.sign(msg).hex()}]
        self.pin = self.repin()

    def test_two_valid_epoch_snapshots_hold_deny(self):
        v = self.check()
        self.assertTrue(v["history_valid"], v["errors"])
        self.assertEqual(v["epochs_checked"], 2)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for field in ("release_authorized", "merge_authorized",
                      "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[field])

    def test_valid_dual_signed_observer_rotation(self):
        self.rotate_observer_b()
        v = self.check()
        self.assertTrue(v["history_valid"], v["errors"])
        self.assertEqual(v["rotations_verified"], 1)

    def test_rotation_old_signature_forged(self):
        self.rotate_observer_b()
        self.history["rotations"][0]["old_signature_ed25519_hex"] = "0" * 128
        self.assertTrue(any(s.startswith("rotation_signature:1:observer-b:old:")
                            for s in self.check()["errors"]))

    def test_rotation_new_signature_forged(self):
        self.rotate_observer_b()
        self.history["rotations"][0]["new_signature_ed25519_hex"] = "0" * 128
        self.assertFalse(self.check()["history_valid"])

    def test_rotation_unattested_denied(self):
        self.rotate_observer_b()
        self.history["rotations"] = []
        self.assertIn("unattested_observer_rotation:1:observer-b", self.check()["errors"])

    def test_revocation_effective_in_second_epoch(self):
        old_pub = self.first["observer_trust"]["observers"]["observer-a"]["public_key_hex"]
        self.revocations["entries"] = [{"public_key_hex": old_pub, "effective_epoch": 8}]
        self.pin = self.repin()
        self.assertIn("revoked_observer_key_used:1:observer-a", self.check()["errors"])

    def test_preexisting_revocation_rejected(self):
        old_pub = self.first["observer_trust"]["observers"]["observer-a"]["public_key_hex"]
        self.revocations["entries"] = [{"public_key_hex": old_pub, "effective_epoch": 7}]
        self.pin = self.repin()
        self.assertIn("revoked_observer_key_used:0:observer-a", self.check()["errors"])

    def test_revocation_of_unused_key_allowed(self):
        self.revocations["entries"] = [{"public_key_hex": "a" * 64, "effective_epoch": 7}]
        self.pin = self.repin()
        self.assertTrue(self.check()["history_valid"], self.check()["errors"])

    def test_unanchored_revocation_registry_rejected(self):
        self.revocations["entries"] = [{"public_key_hex": "a" * 64, "effective_epoch": 8}]
        self.assertIn("independent_revocation_register_mismatch", self.check()["errors"])

    def test_duplicate_revocation_denied(self):
        record = {"public_key_hex": "a" * 64, "effective_epoch": 8}
        self.revocations["entries"] = [record, copy.deepcopy(record)]
        self.pin = self.repin()
        self.assertIn("invalid_or_duplicate_revocation:1", self.check()["errors"])

    def test_epoch_gap_denied(self):
        self.second["epoch"] = 9
        self.assertIn("invalid_or_skipped_epoch:1", self.check()["errors"])

    def test_old_snapshot_rewrite_detected(self):
        self.first["independent_heads"]["heads"]["observer-a"]["minimum_epoch"] = 0
        self.assertIn("independent_first_snapshot_mismatch", self.check()["errors"])

    def test_last_snapshot_rewrite_detected(self):
        self.second["independent_heads"]["heads"]["observer-b"]["minimum_epoch"] = 0
        self.assertIn("independent_last_snapshot_mismatch", self.check()["errors"])

    def test_missing_observer_epoch(self):
        self.second["signed_anchors"]["anchors"].pop()
        self.assertFalse(self.check()["history_valid"])

    def test_orphan_rotation_denied(self):
        self.rotate_observer_b()
        self.second["observer_trust"]["observers"]["observer-b"]["public_key_hex"] = (
            self.first["observer_trust"]["observers"]["observer-b"]["public_key_hex"])
        self.assertFalse(self.check()["history_valid"])

    def test_rotation_binding_mutation_denied(self):
        self.rotate_observer_b()
        self.history["rotations"][0]["old_anchor_sha256"] = "0" * 64
        self.assertIn("rotation_binding_mismatch:1:observer-b", self.check()["errors"])

    def test_corrupted_inner_multiview_denied(self):
        self.second["views"]["views"][0]["history"]["entries"][0][
            "envelope"]["signature_ed25519_hex"] = "0" * 128
        self.assertFalse(self.check()["history_valid"])


if __name__ == "__main__":
    unittest.main()
