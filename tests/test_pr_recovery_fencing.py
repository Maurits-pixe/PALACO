"""GO-20 v41: fenced handoff evidence, split-brain and epoch rollback tests."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pr_audit_integrity import canonical_hash
from pr_recovery_handoff import canonical, digest
from pr_recovery_fencing import SCHEMA, PIN_SCHEMA, check

A, B, C, D = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


class FencingTests(unittest.TestCase):
    def setUp(self):
        self.primary = [
            dict(request_id="one", manifest_sha256=A, pin_sha256=B, segments_sha256=C),
            dict(request_id="two", manifest_sha256=D, pin_sha256=B, segments_sha256=C),
        ]
        self.candidate = copy.deepcopy(self.primary)
        self.handoff_pin = {
            "schema": "palaco.go20-restore-handoff-pin.v1",
            "primary_sha256": digest(canonical(self.primary)), "minimum_rows": 2,
        }
        self.transition = {
            "schema": SCHEMA, "repository": "Maurits-pixe/PALACO",
            "previous_epoch": 7, "candidate_epoch": 8,
            "old_writer_id": "node-primary", "candidate_id": "node-secondary",
            "node_roles": {"node-primary": "fenced", "node-secondary": "candidate"},
            "fencing_ack": {
                "fenced_node_id": "node-primary", "fenced_at_epoch": 8,
                "acknowledged": True, "control_domain": "isolated-fence-controller",
            },
            "handoff_sha256": digest(canonical(self.primary)),
        }
        self.pin = {
            "schema": PIN_SCHEMA, "transition_sha256": canonical_hash(self.transition),
            "minimum_epoch": 8,
            "expected_previous_writer": "node-primary",
            "expected_candidate": "node-secondary",
        }

    def repin(self):
        self.pin["transition_sha256"] = canonical_hash(self.transition)

    def check(self):
        return check(self.primary, self.candidate, self.handoff_pin,
                     self.transition, self.pin)

    def test_valid_evidence_still_denies_transition(self):
        out = self.check()
        self.assertTrue(out["fencing_evidence_valid"], out["errors"])
        self.assertEqual(out["records_verified"], 2)
        self.assertEqual((out["decision"], out["authorization"]), ("HOLD", "DENY"))
        for field in ("fence_performed", "failover_authorized", "promotion_performed",
                      "release_authorized", "merge_authorized",
                      "deployment_authorized", "production_commit_performed"):
            self.assertFalse(out[field])

    def test_missing_fencing_ack(self):
        self.transition["fencing_ack"]["acknowledged"] = False
        self.repin()
        self.assertIn("fencing_ack_missing_or_invalid", self.check()["errors"])

    def test_wrong_fenced_node(self):
        self.transition["fencing_ack"]["fenced_node_id"] = "node-secondary"
        self.repin()
        self.assertFalse(self.check()["fencing_evidence_valid"])

    def test_old_writer_remains_active(self):
        self.transition["node_roles"]["node-primary"] = "writer"
        self.repin()
        self.assertIn("split_brain_or_unfenced_writer", self.check()["errors"])

    def test_two_writers_denied(self):
        self.transition["node_roles"]["node-primary"] = "writer"
        self.transition["node_roles"]["node-secondary"] = "writer"
        self.repin()
        self.assertFalse(self.check()["fencing_evidence_valid"])

    def test_candidate_claims_writer(self):
        self.transition["node_roles"]["node-secondary"] = "writer"
        self.repin()
        self.assertFalse(self.check()["fencing_evidence_valid"])

    def test_epoch_rollback(self):
        self.transition["candidate_epoch"] = 7
        self.repin()
        self.assertIn("epoch_rollback_or_gap", self.check()["errors"])

    def test_epoch_gap(self):
        self.transition["candidate_epoch"] = 10
        self.repin()
        self.assertIn("epoch_rollback_or_gap", self.check()["errors"])

    def test_below_externally_pinned_epoch(self):
        self.pin["minimum_epoch"] = 9
        self.assertIn("epoch_rollback_or_gap", self.check()["errors"])

    def test_boolean_epoch_rejected(self):
        self.transition["candidate_epoch"] = True
        self.repin()
        self.assertIn("epoch_rollback_or_gap", self.check()["errors"])

    def test_same_node_identity(self):
        self.transition["candidate_id"] = "node-primary"
        self.repin()
        self.assertIn("writer_identity_conflict", self.check()["errors"])

    def test_swapped_authority_pin(self):
        self.pin["expected_previous_writer"] = "attacker"
        self.assertIn("writer_identity_conflict", self.check()["errors"])

    def test_unpinned_fencing_evidence(self):
        self.transition["fencing_ack"]["control_domain"] = "replacement"
        self.assertIn("independent_fencing_anchor_mismatch", self.check()["errors"])

    def test_missing_secondary_record(self):
        self.candidate.pop()
        self.assertFalse(self.check()["fencing_evidence_valid"])

    def test_divergent_secondary_record(self):
        self.candidate[0]["segments_sha256"] = A
        self.assertFalse(self.check()["fencing_evidence_valid"])

    def test_replaced_source_anchor(self):
        self.handoff_pin["primary_sha256"] = A
        self.assertFalse(self.check()["fencing_evidence_valid"])

    def test_wrong_snapshot_binding(self):
        self.transition["handoff_sha256"] = A
        self.repin()
        self.assertIn("handoff_binding_mismatch", self.check()["errors"])

    def test_malformed_transition_denied(self):
        self.transition["extra"] = "invalid"
        self.repin()
        self.assertIn("invalid_transition", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
