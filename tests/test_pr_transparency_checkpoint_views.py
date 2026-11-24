"""GO-20 v45: signed external checkpoint observations and fork detection."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_transparency_checkpoint_views import (
    SCHEMA, TRUST_SCHEMA, PIN_SCHEMA, STATEMENT_SCHEMA,
    CHECKPOINT_SCHEMA, assess,
)
from test_pr_signed_revocation_fork import ForkProofTests


class InvalidCheckpointTests(unittest.TestCase):
    def test_missing_sources_hold(self):
        out = assess(*([None] * 10))
        self.assertFalse(out["transparency_evidence_valid"])
        self.assertEqual((out["decision"], out["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(out["checkpoint_published"])


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        base = ForkProofTests("test_equivalent_histories_still_denied_authority")
        base.setUp()
        self.base = base
        self.private = {name: Ed25519PrivateKey.generate()
                        for name in ("keeper-a", "keeper-b", "keeper-c")}
        self.trust = {"schema": TRUST_SCHEMA, "witnesses": {}}
        for name, key in self.private.items():
            self.trust["witnesses"][name] = {
                "public_key_hex": key.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw).hex(),
                "organization_id": "organization-" + name,
                "domain_id": "domain-" + name, "status": "active",
            }
        self.checkpoint = {
            "schema": CHECKPOINT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "sequence": 44, "last_epoch": 9,
            "history_sha256": canonical_hash(base.left),
            "revocations_sha256": canonical_hash(base.revocations),
        }
        self.pin = {
            "schema": PIN_SCHEMA,
            "trust_sha256": canonical_hash(self.trust),
            "checkpoint_sha256": canonical_hash(self.checkpoint),
            "minimum_sequence": 44, "quorum": 2,
        }
        self.views = {"schema": SCHEMA, "observations": []}
        for observer in ("observer-east", "observer-west"):
            view = {"observer_id": observer,
                    "checkpoint": copy.deepcopy(self.checkpoint),
                    "signatures": []}
            self.views["observations"].append(view)
            self.sign(view)

    def sign(self, view):
        view["signatures"] = []
        for witness_id in ("keeper-a", "keeper-b"):
            statement = {
                "schema": STATEMENT_SCHEMA,
                "observer_id": view["observer_id"],
                "checkpoint_sha256": canonical_hash(view["checkpoint"]),
                "trust_sha256": canonical_hash(self.trust),
                "witness_id": witness_id,
                "decision": "HOLD", "authorization": "DENY",
            }
            signature = self.private[witness_id].sign(
                bytes.fromhex(canonical_hash(statement))).hex()
            view["signatures"].append({
                "witness_id": witness_id,
                "signature_ed25519_hex": signature,
            })

    def check(self):
        b = self.base
        return assess(b.left, b.left_pin, b.right, b.right_pin,
                      b.revocations, b.signed, b.pin, self.views,
                      self.trust, self.pin)

    def test_valid_two_views_still_deny_authority(self):
        out = self.check()
        self.assertTrue(out["transparency_evidence_valid"], out["errors"])
        self.assertEqual((out["views_verified"], out["signatures_verified"]), (2, 4))
        for name in ("checkpoint_published", "fence_performed", "failover_authorized",
                     "promotion_performed", "release_authorized",
                     "merge_authorized", "deployment_authorized",
                     "production_commit_performed"):
            self.assertFalse(out[name])

    def test_signed_conflicting_head_detected(self):
        view = self.views["observations"][1]
        view["checkpoint"]["history_sha256"] = "f" * 64
        self.sign(view)
        out = self.check()
        self.assertIn("equivocation_or_unpinned_checkpoint:1", out["errors"])
        self.assertIn("checkpoint_history_or_revocation_mismatch:1", out["errors"])

    def test_signed_distinct_sequence_rejected(self):
        view = self.views["observations"][1]
        view["checkpoint"]["sequence"] = 45
        self.sign(view)
        self.assertIn("equivocation_or_unpinned_checkpoint:1", self.check()["errors"])

    def test_missing_witness_signature(self):
        self.views["observations"][1]["signatures"].pop()
        self.assertIn("insufficient_witness_quorum:1", self.check()["errors"])

    def test_forged_witness_signature(self):
        self.views["observations"][0]["signatures"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertFalse(self.check()["transparency_evidence_valid"])

    def test_duplicate_witness(self):
        v = self.views["observations"][0]
        v["signatures"][1] = copy.deepcopy(v["signatures"][0])
        self.assertFalse(self.check()["transparency_evidence_valid"])

    def test_duplicate_observer(self):
        self.views["observations"][1]["observer_id"] = "observer-east"
        self.assertIn("invalid_view:1", self.check()["errors"])

    def test_revoked_witness(self):
        self.trust["witnesses"]["keeper-b"]["status"] = "revoked"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        for view in self.views["observations"]:
            self.sign(view)
        self.assertFalse(self.check()["transparency_evidence_valid"])

    def test_duplicate_custody_domain(self):
        self.trust["witnesses"]["keeper-b"]["domain_id"] = "domain-keeper-a"
        self.pin["trust_sha256"] = canonical_hash(self.trust)
        for view in self.views["observations"]:
            self.sign(view)
        self.assertIn("overlapping_witness_custody:0:keeper-b", self.check()["errors"])

    def test_registry_anchor_tampered(self):
        self.trust["witnesses"]["keeper-a"]["domain_id"] = "attacker"
        self.assertIn("witness_trust_anchor_mismatch", self.check()["errors"])

    def test_minimum_sequence_rollback(self):
        self.pin["minimum_sequence"] = 45
        self.assertFalse(self.check()["transparency_evidence_valid"])

    def test_quorum_floor_raised(self):
        self.pin["quorum"] = 3
        self.assertIn("insufficient_witness_quorum:0", self.check()["errors"])

    def test_boolean_quorum_denied(self):
        self.pin["quorum"] = True
        self.assertIn("invalid_independent_checkpoint_pin", self.check()["errors"])

    def test_revocations_checkpoint_mismatch(self):
        self.views["observations"][0]["checkpoint"]["revocations_sha256"] = "0" * 64
        self.sign(self.views["observations"][0])
        self.assertFalse(self.check()["transparency_evidence_valid"])

    def test_underlying_v44_fork_denied(self):
        self.base.fork_with_valid_alternative_votes()
        self.assertTrue(any(e.startswith("v44:") for e in self.check()["errors"]))

    def test_unknown_witness_id_denied(self):
        self.views["observations"][1]["signatures"][1]["witness_id"] = "intruder"
        self.assertFalse(self.check()["transparency_evidence_valid"])


if __name__ == "__main__":
    unittest.main()
