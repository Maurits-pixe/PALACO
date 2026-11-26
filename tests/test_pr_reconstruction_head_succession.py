"""GO-20 v61: immutable historical head, reviewer revocation and fork tests."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_reconstruction_head_succession import SCHEMA, PIN_SCHEMA, HEAD_SCHEMA, ZERO, assess
from test_pr_reconstruction_head_witnesses import HeadWitnessTests


class InvalidHeadSuccessionTests(unittest.TestCase):
    def test_null_denied(self):
        result = assess(None, None, None, None, None)
        self.assertFalse(result["succession_evidence_valid"])
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))


class HeadSuccessionTests(unittest.TestCase):
    def setUp(self):
        base = HeadWitnessTests("test_two_signed_anchors_remain_hold")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        evidence = {"v59_sources": base.sources, "head_witnesses": base.evidence,
                    "witness_trust": base.trust, "reviewer_revocations": base.revocations,
                    "independent_pin": base.pin}
        first = {"round": 40, "previous_sha256": ZERO,
                 "evidence": copy.deepcopy(evidence)}
        second = {"round": 41, "previous_sha256": canonical_hash(first),
                  "evidence": copy.deepcopy(evidence)}
        self.left = {"schema": SCHEMA, "rounds": [first, second]}
        self.right = copy.deepcopy(self.left)
        self.pin_left = self.repin(self.left)
        self.pin_right = self.repin(self.right)
        self.head = {"schema": HEAD_SCHEMA, "history_sha256": canonical_hash(self.left),
                     "minimum_last_round": 41, "minimum_witnesses": 2}

    def repin(self, history):
        start = history["rounds"][0]["evidence"]
        return {"schema": PIN_SCHEMA, "first_round": 40, "last_round": 41,
                "first_sha256": canonical_hash(history["rounds"][0]),
                "last_sha256": canonical_hash(history["rounds"][-1]),
                "history_sha256": canonical_hash(history),
                "v59_sha256": canonical_hash(start["v59_sources"]),
                "witness_trust_sha256": canonical_hash(start["witness_trust"]),
                "minimum_witnesses": 2}

    def check(self):
        return assess(self.left, self.pin_left, self.right, self.pin_right, self.head)

    def test_valid_history_remains_hold(self):
        v = self.check()
        self.assertTrue(v["succession_evidence_valid"], v["errors"])
        self.assertEqual(v["rounds_verified"], 4)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for k in ("revocations_enforced_in_production", "recovery_performed",
                  "recovery_authorized", "trust_registry_promoted",
                  "merge_authorized", "deployment_authorized",
                  "production_commit_performed"):
            self.assertFalse(v[k])

    def test_missing_round(self):
        self.right["rounds"].pop()
        self.assertFalse(self.check()["succession_evidence_valid"])

    def test_skipped_sequence(self):
        self.right["rounds"][1]["round"] = 42
        self.assertIn("right:invalid_or_missing_round:1", self.check()["errors"])

    def test_link_tamper_even_when_repinned(self):
        self.right["rounds"][1]["previous_sha256"] = "f"*64
        self.pin_right = self.repin(self.right)
        self.assertIn("right:broken_succession_link:1", self.check()["errors"])

    def test_genesis_link(self):
        self.left["rounds"][0]["previous_sha256"] = "a"*64
        self.assertIn("left:invalid_genesis", self.check()["errors"])

    def test_first_anchor(self):
        self.pin_left["first_sha256"] = "a"*64
        self.assertIn("left:first_round_anchor_mismatch", self.check()["errors"])

    def test_last_anchor(self):
        self.pin_right["last_sha256"] = "a"*64
        self.assertIn("right:last_round_anchor_mismatch", self.check()["errors"])

    def test_full_history_anchor(self):
        self.pin_right["history_sha256"] = "a"*64
        self.assertIn("right:independent_history_anchor_mismatch", self.check()["errors"])

    def test_replaced_witness_public_key(self):
        self.right["rounds"][1]["evidence"]["witness_trust"]["members"]["keeper-a"]["public_key_hex"] = "f"*64
        self.assertIn("right:witness_trust_or_v59_substitution:1", self.check()["errors"])

    def test_modified_underlying_review_history(self):
        self.right["rounds"][1]["evidence"]["v59_sources"]["left"]["rounds"].pop()
        self.assertIn("right:witness_trust_or_v59_substitution:1", self.check()["errors"])

    def test_forged_v60_signature(self):
        self.right["rounds"][1]["evidence"]["head_witnesses"]["witnesses"][0]["signature_ed25519_hex"] = "0"*128
        self.assertTrue(any(x.startswith("right:v60:1:") for x in self.check()["errors"]))

    def test_conflicting_recovery_grant(self):
        self.right["rounds"][1]["evidence"]["head_witnesses"]["decisions"][0]["authorization"] = "ALLOW"
        self.assertFalse(self.check()["succession_evidence_valid"])

    def test_revision_of_recovery_assertion(self):
        self.right["rounds"][1]["evidence"]["head_witnesses"]["decisions"].reverse()
        self.right["rounds"][1]["previous_sha256"] = canonical_hash(self.right["rounds"][0])
        self.pin_right = self.repin(self.right)
        self.assertIn("right:conflicting_recovery_assertion:1", self.check()["errors"])

    def test_independently_valid_but_divergent_heads(self):
        for round_item in self.right["rounds"]:
            round_item["evidence"]["head_witnesses"]["witnesses"].reverse()
        self.right["rounds"][1]["previous_sha256"] = canonical_hash(self.right["rounds"][0])
        self.pin_right = self.repin(self.right)
        v = self.check()
        self.assertIn("conflicting_reconstruction_head_histories", v["errors"])
        self.assertIn("right_external_head_mismatch", v["errors"])

    def test_removed_old_revocation(self):
        old = {"reviewer_id": "retired", "public_key_hex": "f"*64, "effective_round": 30}
        first, second = self.right["rounds"]
        first["evidence"]["reviewer_revocations"]["entries"].append(old)
        second["evidence"]["reviewer_revocations"]["entries"] = []
        self.assertFalse(self.check()["succession_evidence_valid"])

    def test_round_floor_rollback(self):
        self.head["minimum_last_round"] = 42
        self.assertIn("independent_head_rollback", self.check()["errors"])

    def test_quorum_external_floor(self):
        self.head["minimum_witnesses"] = 3
        self.assertIn("external_witness_floor_downgrade", self.check()["errors"])

    def test_bool_floor_invalid(self):
        self.pin_right["minimum_witnesses"] = True
        self.assertIn("right:invalid_history_pin", self.check()["errors"])

    def test_missing_original_v60_evidence(self):
        self.right["rounds"][1]["evidence"]["head_witnesses"]["witnesses"].pop()
        self.assertTrue(any(x.startswith("right:v60:1:") for x in self.check()["errors"]))

    def test_outside_head_tamper(self):
        self.head["history_sha256"] = "f"*64
        self.assertIn("left_external_head_mismatch", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
