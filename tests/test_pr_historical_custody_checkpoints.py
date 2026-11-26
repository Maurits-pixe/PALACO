"""GO-20 v64: independently signed checkpoint publication evidence regressions."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_historical_custody_checkpoints import (
    SCHEMA, TRUST_SCHEMA, REVOKE_SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA, assess
)
from test_pr_head_custody_succession import CustodyHistoryTests


class MalformedCheckpointTests(unittest.TestCase):
    def test_missing_all_denies(self):
        v = assess(None, None, None, None, None, None)
        self.assertFalse(v["checkpoint_evidence_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))


class PublicationCheckpointTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        base = CustodyHistoryTests("test_matching_history_still_deny")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        self.sources = {"left": base.left, "left_pin": base.left_pin,
                        "right": base.right, "right_pin": base.right_pin,
                        "head": base.head}
        self.secrets = {mid: Ed25519PrivateKey.generate()
                        for mid in ("witness-a", "witness-b", "witness-c")}
        self.trust = {"schema": TRUST_SCHEMA, "members": {}}
        for mid, secret in self.secrets.items():
            self.trust["members"][mid] = {
                "public_key_hex": secret.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "organization_id": "org-" + mid,
                "domain_id": "domain-" + mid,
                "status": "active",
            }
        self.revocations = {"schema": REVOKE_SCHEMA, "entries": []}
        self.pin = {
            "schema": PIN_SCHEMA,
            "v63_sha256": canonical_hash(self.sources),
            "trust_sha256": canonical_hash(self.trust),
            "revocations_sha256": canonical_hash(self.revocations),
            "left_sha256": "0"*64,
            "right_sha256": "0"*64,
            "minimum_snapshot": 51, "quorum": 2,
        }
        self.left = {"schema": SCHEMA, "checkpoints": []}
        for snap in base.left["snapshots"]:
            record = {"snapshot": snap["snapshot"],
                      "snapshot_sha256": canonical_hash(snap),
                      "signatures": [
                          {"witness_id": wid,
                           "signature_ed25519_hex": self.sign(snap, wid)}
                          for wid in ("witness-a", "witness-b")],
                     }
            self.left["checkpoints"].append(record)
        self.right = copy.deepcopy(self.left)
        self.repin()

    def sign(self, snap, wid):
        statement = {
            "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "snapshot": snap["snapshot"],
            "snapshot_sha256": canonical_hash(snap),
            "previous_sha256": snap["previous_sha256"],
            "v63_sha256": self.pin["v63_sha256"],
            "trust_sha256": self.pin["trust_sha256"],
            "revocations_sha256": self.pin["revocations_sha256"],
            "witness_id": wid, "decision": "HOLD", "authorization": "DENY",
        }
        return self.secrets[wid].sign(bytes.fromhex(canonical_hash(statement))).hex()

    def repin(self):
        self.pin["left_sha256"] = canonical_hash(self.left)
        self.pin["right_sha256"] = canonical_hash(self.right)

    def resign(self):
        for view in (self.left, self.right):
            for i, record in enumerate(view["checkpoints"]):
                snap = self.base.left["snapshots"][i]
                for vote in record["signatures"]:
                    vote["signature_ed25519_hex"] = self.sign(snap, vote["witness_id"])

    def check(self):
        return assess(self.sources, self.left, self.right,
                      self.trust, self.revocations, self.pin)

    def test_complete_signed_history_still_denies(self):
        out = self.check()
        self.assertTrue(out["checkpoint_evidence_valid"], out["errors"])
        self.assertEqual((out["checkpoints_verified"], out["witness_signatures_verified"]), (4, 8))
        for flag in ("live_publication_verified", "external_custody_verified",
                     "storage_access_verified", "revocation_enforced_in_production",
                     "recovery_authorized", "history_restored", "merge_authorized",
                     "deployment_authorized", "production_commit_performed"):
            self.assertFalse(out[flag])

    def test_missing_checkpoint(self):
        self.right["checkpoints"].pop()
        self.repin()
        self.assertIn("right:missing_historical_publications", self.check()["errors"])

    def test_wrong_checkpoint_hash(self):
        self.right["checkpoints"][0]["snapshot_sha256"] = "f"*64
        self.repin()
        self.assertIn("right:invalid_checkpoint:0", self.check()["errors"])

    def test_missing_signature(self):
        self.right["checkpoints"][0]["signatures"].pop()
        self.repin()
        self.assertIn("right:invalid_checkpoint:0", self.check()["errors"])

    def test_forged_signature(self):
        self.right["checkpoints"][0]["signatures"][0]["signature_ed25519_hex"] = "0"*128
        self.repin()
        self.assertIn("right:invalid_witness_signature:0:witness-a", self.check()["errors"])

    def test_signature_replay_across_snapshots(self):
        self.right["checkpoints"][1]["signatures"][0]["signature_ed25519_hex"] = (
            self.right["checkpoints"][0]["signatures"][0]["signature_ed25519_hex"])
        self.repin()
        self.assertIn("right:invalid_witness_signature:1:witness-a", self.check()["errors"])

    def test_duplicate_witness(self):
        self.right["checkpoints"][0]["signatures"][1] = copy.deepcopy(
            self.right["checkpoints"][0]["signatures"][0])
        self.repin()
        self.assertIn("right:duplicate_or_unknown_witness:0:1", self.check()["errors"])

    def test_revoked_witness(self):
        self.trust["members"]["witness-b"]["status"] = "revoked"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.resign()
        self.repin()
        self.assertIn("right:invalid_witness:0:witness-b", self.check()["errors"])

    def test_shared_organization(self):
        self.trust["members"]["witness-b"]["organization_id"] = "org-witness-a"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        self.resign()
        self.repin()
        self.assertIn("left:overlapping_witness_custody:0:witness-b", self.check()["errors"])

    def test_external_witness_key_replacement(self):
        self.trust["members"]["witness-a"]["public_key_hex"] = "f"*64
        self.assertIn("independent_checkpoint_anchor_mismatch", self.check()["errors"])

    def test_revoked_historical_custodian(self):
        member = self.base.left["snapshots"][1]["sources"]["trust"]["members"]["archive-a"]
        self.revocations["entries"].append({
            "custodian_id": "archive-a",
            "public_key_hex": member["public_key_hex"],
            "effective_snapshot": 51,
        })
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.resign()
        self.repin()
        self.assertIn("revoked_custodian_reused:1:archive-a", self.check()["errors"])

    def test_duplicate_revocation(self):
        item = {"custodian_id": "retired", "public_key_hex": "f"*64,
                "effective_snapshot": 50}
        self.revocations["entries"] = [item, copy.deepcopy(item)]
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.resign()
        self.repin()
        self.assertIn("duplicate_revocation:1", self.check()["errors"])

    def test_boolean_revocation_snapshot_rejected(self):
        self.revocations["entries"] = [
            {"custodian_id": "retired", "public_key_hex": "f"*64,
             "effective_snapshot": True}]
        self.pin["revocations_sha256"] = canonical_hash(self.revocations)
        self.resign()
        self.repin()
        self.assertIn("invalid_revocation:0", self.check()["errors"])

    def test_revocation_removal_changes_external_anchor(self):
        self.revocations["entries"].append(
            {"custodian_id": "retired", "public_key_hex": "f"*64,
             "effective_snapshot": 50})
        self.assertIn("independent_checkpoint_anchor_mismatch", self.check()["errors"])

    def test_two_valid_but_split_publication_views(self):
        self.right["checkpoints"][0]["signatures"].reverse()
        self.repin()
        self.assertIn("split_publication_histories", self.check()["errors"])

    def test_minimum_snapshot_rollback(self):
        self.pin["minimum_snapshot"] = 52
        self.assertIn("snapshot_rollback", self.check()["errors"])

    def test_witness_quorum_upgrade(self):
        self.pin["quorum"] = 3
        self.repin()
        self.assertIn("left:insufficient_publication_witnesses:0", self.check()["errors"])

    def test_boolean_quorum_rejected(self):
        self.pin["quorum"] = True
        self.assertIn("invalid_external_checkpoint_pin", self.check()["errors"])

    def test_original_v63_broken(self):
        self.sources["right"]["snapshots"].pop()
        self.pin["v63_sha256"] = canonical_hash(self.sources)
        self.resign()
        self.repin()
        self.assertTrue(any(x.startswith("v63:") for x in self.check()["errors"]))

    def test_unpinned_publication_change(self):
        self.right["checkpoints"][0]["signatures"].reverse()
        self.assertIn("independent_checkpoint_anchor_mismatch", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
