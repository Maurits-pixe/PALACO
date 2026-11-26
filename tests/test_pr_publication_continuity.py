"""GO-20 v65: signed publication continuity and split observer regressions."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_publication_continuity import SCHEMA,PIN_SCHEMA,HEAD_SCHEMA,ZERO,assess
from test_pr_historical_custody_checkpoints import PublicationCheckpointTests


class MalformedContinuityTests(unittest.TestCase):
    def test_null_deny(self):
        r=assess(None,None,None,None,None)
        self.assertFalse(r["publication_evidence_valid"])
        self.assertEqual((r["decision"],r["authorization"]),("HOLD","DENY"))


class PublicationContinuityTests(unittest.TestCase):
    def setUp(self):
        base=PublicationCheckpointTests("test_complete_signed_history_still_denies")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base=base
        source={"v63_sources":base.sources,"left":base.left,"right":base.right,
                "witness_trust":base.trust,"revocations":base.revocations,
                "independent_pin":base.pin}
        first={"round":60,"previous_sha256":ZERO,"evidence":copy.deepcopy(source)}
        second={"round":61,"previous_sha256":canonical_hash(first),
                "evidence":copy.deepcopy(source)}
        self.left={"schema":SCHEMA,"rounds":[first,second]}
        self.right=copy.deepcopy(self.left)
        self.left_pin=self.repin(self.left)
        self.right_pin=self.repin(self.right)
        self.head={"schema":HEAD_SCHEMA,"expected_history_sha256":canonical_hash(self.left),
                   "minimum_last_round":61,"minimum_quorum":2}

    def repin(self,view):
        data=view["rounds"][0]["evidence"]
        return {"schema":PIN_SCHEMA,"first_round":60,"last_round":61,
                "first_sha256":canonical_hash(view["rounds"][0]),
                "last_sha256":canonical_hash(view["rounds"][-1]),
                "history_sha256":canonical_hash(view),
                "v63_sha256":canonical_hash(data["v63_sources"]),
                "publication_left_sha256":canonical_hash(data["left"]),
                "publication_right_sha256":canonical_hash(data["right"]),
                "witness_trust_sha256":canonical_hash(data["witness_trust"]),
                "minimum_quorum":2}

    def check(self):
        return assess(self.left,self.left_pin,self.right,self.right_pin,self.head)

    def test_valid_history_still_hold_deny(self):
        v=self.check()
        self.assertTrue(v["publication_evidence_valid"],v["errors"])
        self.assertEqual(v["rounds_verified"],4)
        self.assertEqual((v["decision"],v["authorization"]),("HOLD","DENY"))
        for k in ("network_publication_verified","physical_archive_verified",
                  "revocation_enforced_in_production","recovery_authorized",
                  "failover_authorized","merge_authorized","deployment_authorized",
                  "production_commit_performed"):
            self.assertFalse(v[k])

    def test_missing_round(self):
        self.right["rounds"].pop()
        self.assertIn("right:invalid_continuity_view",self.check()["errors"])

    def test_skipped_round(self):
        self.right["rounds"][1]["round"]=62
        self.assertIn("right:invalid_or_missing_round:1",self.check()["errors"])

    def test_broken_link_repin(self):
        self.right["rounds"][1]["previous_sha256"]="f"*64
        self.right_pin=self.repin(self.right)
        self.assertIn("right:broken_round_link:1",self.check()["errors"])

    def test_genesis_link(self):
        self.left["rounds"][0]["previous_sha256"]="f"*64
        self.assertIn("left:invalid_genesis_link",self.check()["errors"])

    def test_first_anchor(self):
        self.left_pin["first_sha256"]="f"*64
        self.assertIn("left:first_round_anchor_mismatch",self.check()["errors"])

    def test_last_anchor(self):
        self.right_pin["last_sha256"]="f"*64
        self.assertIn("right:last_round_anchor_mismatch",self.check()["errors"])

    def test_trust_key_replaced(self):
        self.right["rounds"][1]["evidence"]["witness_trust"]["members"]["witness-a"]["public_key_hex"]="f"*64
        self.assertIn("right:publication_or_trust_substitution:1",self.check()["errors"])

    def test_v63_history_modified(self):
        self.right["rounds"][1]["evidence"]["v63_sources"]["right"]["snapshots"].pop()
        self.assertIn("right:publication_or_trust_substitution:1",self.check()["errors"])

    def test_unauthorized_checkpoint_mutation(self):
        self.right["rounds"][1]["evidence"]["right"]["checkpoints"][0]["signatures"][0]["signature_ed25519_hex"]="0"*128
        self.assertIn("right:publication_or_trust_substitution:1",self.check()["errors"])

    def test_missing_original_publication(self):
        self.right["rounds"][1]["evidence"]["left"]["checkpoints"].pop()
        self.assertFalse(self.check()["publication_evidence_valid"])

    def test_independently_valid_but_forked_views(self):
        # Both views individually validate v64, but carry different
        # signature ordering. The original signed statements still verify.
        for rec in self.right["rounds"]:
            evidence=rec["evidence"]
            evidence["left"]["checkpoints"][0]["signatures"].reverse()
            evidence["right"]["checkpoints"][0]["signatures"].reverse()
            evidence["independent_pin"]["left_sha256"]=canonical_hash(evidence["left"])
            evidence["independent_pin"]["right_sha256"]=canonical_hash(evidence["right"])
        self.right["rounds"][1]["previous_sha256"]=canonical_hash(self.right["rounds"][0])
        self.right_pin=self.repin(self.right)
        v=self.check()
        self.assertIn("contradictory_publication_continuity",v["errors"])

    def test_external_rollback_floor(self):
        self.head["minimum_last_round"]=62
        self.assertIn("independent_history_rollback",self.check()["errors"])

    def test_external_quorum_floor(self):
        self.head["minimum_quorum"]=3
        self.assertIn("independent_quorum_downgrade",self.check()["errors"])

    def test_boolean_quorum(self):
        self.left_pin["minimum_quorum"]=True
        self.assertIn("left:invalid_continuity_pin",self.check()["errors"])

    def test_boolean_head_round(self):
        self.head["minimum_last_round"]=True
        self.assertIn("invalid_independent_head",self.check()["errors"])

    def test_head_hash_conflict(self):
        self.head["expected_history_sha256"]="f"*64
        self.assertIn("left_external_head_mismatch",self.check()["errors"])

    def test_underlying_v64_invalid(self):
        evidence=self.right["rounds"][1]["evidence"]
        evidence["revocations"]["entries"].append(
            {"custodian_id":"archive-a","public_key_hex":
             evidence["v63_sources"]["left"]["snapshots"][1]["sources"]["trust"]["members"]["archive-a"]["public_key_hex"],
             "effective_snapshot":51})
        evidence["independent_pin"]["revocations_sha256"]=canonical_hash(evidence["revocations"])
        # Signatures remain bound to the old revocation hash, and must fail.
        self.assertTrue(any(x.startswith("right:v64:1:") for x in self.check()["errors"]))


if __name__=="__main__":
    unittest.main()
