"""GO-20 v43: historic Ed25519 quorum, effective revocation and rotation tests."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_fencing_quorum_history import (
    SCHEMA, PIN_SCHEMA, REVOKE_SCHEMA, ROTATE_SCHEMA, verify_history,
)
from pr_signed_fencing_quorum import verify_quorum
from test_pr_signed_fencing_quorum import SignedQuorumTests


class MalformedHistoryTests(unittest.TestCase):
    def test_null_history_fails_closed(self):
        v = verify_history(None, None, None)
        self.assertFalse(v["history_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["failover_authorized"])

    def test_invalid_pin_fails_closed(self):
        v = verify_history({"schema": SCHEMA, "snapshots": [{}, {}], "rotations": []},
                           {}, {})
        self.assertIn("invalid_external_history_pin", v["errors"])


class HistoricalQuorumTests(unittest.TestCase):
    def setUp(self):
        base = SignedQuorumTests("test_valid_signatures_still_hold_deny")
        base.setUp()
        self.base = base
        self.first = {
            "epoch": 8, "primary": copy.deepcopy(base.primary),
            "candidate": copy.deepcopy(base.candidate),
            "handoff_pin": copy.deepcopy(base.handoff_pin),
            "transition": copy.deepcopy(base.transition),
            "transition_pin": copy.deepcopy(base.transition_pin),
            "signed_votes": copy.deepcopy(base.signed),
            "trust": copy.deepcopy(base.trust),
            "independent_pin": copy.deepcopy(base.pin),
        }
        base.transition["previous_epoch"] = 8
        base.transition["candidate_epoch"] = 9
        base.transition["old_writer_id"] = "node-secondary"
        base.transition["candidate_id"] = "node-tertiary"
        base.transition["node_roles"] = {
            "node-secondary": "fenced", "node-tertiary": "candidate",
        }
        base.transition["fencing_ack"] = {
            "fenced_node_id": "node-secondary",
            "fenced_at_epoch": 9, "acknowledged": True,
            "control_domain": "isolated-fence-controller",
        }
        base.transition_pin["transition_sha256"] = canonical_hash(base.transition)
        base.transition_pin["minimum_epoch"] = 9
        base.transition_pin["expected_previous_writer"] = "node-secondary"
        base.transition_pin["expected_candidate"] = "node-tertiary"
        base.pin["minimum_epoch"] = 9
        base.repin()
        base.resign()
        self.second = {
            "epoch": 9, "primary": copy.deepcopy(base.primary),
            "candidate": copy.deepcopy(base.candidate),
            "handoff_pin": copy.deepcopy(base.handoff_pin),
            "transition": copy.deepcopy(base.transition),
            "transition_pin": copy.deepcopy(base.transition_pin),
            "signed_votes": copy.deepcopy(base.signed),
            "trust": copy.deepcopy(base.trust),
            "independent_pin": copy.deepcopy(base.pin),
        }
        self.history = {"schema": SCHEMA, "snapshots": [self.first, self.second],
                        "rotations": []}
        self.revocations = {"schema": REVOKE_SCHEMA, "entries": []}
        self.pin = self.repin()

    def repin(self):
        self.pin = {
            "schema": PIN_SCHEMA, "first_epoch": 8, "last_epoch": 9,
            "first_snapshot_sha256": canonical_hash(self.first),
            "last_snapshot_sha256": canonical_hash(self.second),
            "revocations_sha256": canonical_hash(self.revocations),
            "history_sha256": canonical_hash(self.history),
        }
        return self.pin

    def check(self):
        return verify_history(self.history, self.pin, self.revocations)

    def resign_second(self):
        s = self.second
        s["independent_pin"]["trust_sha256"] = canonical_hash(s["trust"])
        s["signed_votes"]["votes"] = [self.base.sign("controller"), self.base.sign("observer-one")]

    def rotate_observer(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        mid = "observer-one"
        old_secret = self.base.secret[mid]
        new_secret = Ed25519PrivateKey.generate()
        old_pub = self.first["trust"]["members"][mid]["public_key_hex"]
        new_pub = new_secret.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.second["trust"]["members"][mid]["public_key_hex"] = new_pub
        self.base.secret[mid] = new_secret
        self.base.trust["members"][mid]["public_key_hex"] = new_pub
        self.base.repin()
        self.resign_second()
        data = {
            "epoch": 9, "member_id": mid,
            "old_public_key_hex": old_pub, "new_public_key_hex": new_pub,
            "old_trust_sha256": canonical_hash(self.first["trust"]),
            "new_trust_sha256": canonical_hash(self.second["trust"]),
        }
        msg = bytes.fromhex(canonical_hash({"schema": ROTATE_SCHEMA, **data}))
        self.history["rotations"] = [{**data,
            "old_signature_ed25519_hex": old_secret.sign(msg).hex(),
            "new_signature_ed25519_hex": new_secret.sign(msg).hex()}]
        self.repin()

    def test_two_epoch_quorum_history(self):
        v = self.check()
        self.assertTrue(v["history_valid"], v["errors"])
        self.assertEqual(v["epochs_verified"], 2)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_valid_dual_signed_rotation(self):
        self.rotate_observer()
        v = self.check()
        self.assertTrue(v["history_valid"], v["errors"])
        self.assertEqual(v["rotations_verified"], 1)

    def test_missing_rotation(self):
        self.rotate_observer()
        self.history["rotations"] = []
        self.repin()
        self.assertIn("unsigned_key_rotation:1:observer-one", self.check()["errors"])

    def test_forged_old_rotation_signature(self):
        self.rotate_observer()
        self.history["rotations"][0]["old_signature_ed25519_hex"] = "0" * 128
        self.repin()
        self.assertIn("rotation_signature_invalid:1:observer-one:old", self.check()["errors"])

    def test_forged_new_rotation_signature(self):
        self.rotate_observer()
        self.history["rotations"][0]["new_signature_ed25519_hex"] = "0" * 128
        self.repin()
        self.assertIn("rotation_signature_invalid:1:observer-one:new", self.check()["errors"])

    def test_key_reuse_after_effective_revocation(self):
        key = self.second["trust"]["members"]["controller"]["public_key_hex"]
        self.revocations["entries"] = [{"public_key_hex": key, "effective_epoch": 9}]
        self.repin()
        self.assertIn("revoked_key_reused:1:controller", self.check()["errors"])

    def test_revocation_before_first_epoch(self):
        key = self.first["trust"]["members"]["controller"]["public_key_hex"]
        self.revocations["entries"] = [{"public_key_hex": key, "effective_epoch": 8}]
        self.repin()
        self.assertIn("revoked_key_reused:0:controller", self.check()["errors"])

    def test_unanchored_revocation_change(self):
        self.revocations["entries"] = [{"public_key_hex": "a" * 64, "effective_epoch": 9}]
        self.assertIn("revocation_anchor_mismatch", self.check()["errors"])

    def test_unused_revoked_key_allowed(self):
        self.revocations["entries"] = [{"public_key_hex": "a" * 64, "effective_epoch": 9}]
        self.repin()
        self.assertTrue(self.check()["history_valid"], self.check()["errors"])

    def test_duplicate_revocation(self):
        item = {"public_key_hex": "a" * 64, "effective_epoch": 9}
        self.revocations["entries"] = [item, copy.deepcopy(item)]
        self.repin()
        self.assertIn("invalid_or_duplicate_revocation:1", self.check()["errors"])

    def test_quorum_downgrade(self):
        self.second["independent_pin"]["minimum_signatures"] = 1
        self.repin()
        self.assertFalse(self.check()["history_valid"])

    def test_epoch_rollback(self):
        self.second["epoch"] = 8
        self.repin()
        self.assertIn("invalid_or_skipped_epoch:1", self.check()["errors"])

    def test_changed_first_snapshot_anchor(self):
        self.first["handoff_pin"]["minimum_rows"] = 1
        self.assertIn("first_snapshot_anchor_mismatch", self.check()["errors"])

    def test_changed_last_snapshot_anchor(self):
        self.second["handoff_pin"]["minimum_rows"] = 1
        self.assertIn("last_snapshot_anchor_mismatch", self.check()["errors"])

    def test_handoff_lineage_break(self):
        self.second["transition"]["old_writer_id"] = "attacker"
        self.repin()
        self.assertFalse(self.check()["history_valid"])

    def test_orphan_rotation(self):
        self.rotate_observer()
        self.history["rotations"][0]["member_id"] = "controller"
        self.repin()
        self.assertIn("orphan_rotation", self.check()["errors"])

    def test_history_anchor_mismatch(self):
        self.pin["history_sha256"] = "a" * 64
        self.assertIn("independent_history_mismatch", self.check()["errors"])

    def test_forged_quorum_vote(self):
        self.second["signed_votes"]["votes"][0]["signature_ed25519_hex"] = "0" * 128
        self.repin()
        self.assertFalse(self.check()["history_valid"])


if __name__ == "__main__":
    unittest.main()
