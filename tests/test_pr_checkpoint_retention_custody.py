"""GO-20 v47: negative tests for offline retention and custody availability."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_checkpoint_retention_custody import SCHEMA,PIN_SCHEMA,STATEMENT_SCHEMA,assess
from test_pr_checkpoint_receipt_continuity import ReceiptContinuityTests

class InvalidRetentionTests(unittest.TestCase):
    def test_missing_sources(self):
        v=assess(*([None]*7))
        self.assertFalse(v["custody_evidence_valid"])
        self.assertEqual((v["decision"],v["authorization"]),("HOLD","DENY"))
        self.assertFalse(v["restoration_performed"])

class CustodyTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
        b=ReceiptContinuityTests("test_complete_chain_remains_hold")
        b.setUp()
        self.b=b
        self.secrets={mid:Ed25519PrivateKey.generate() for mid in ("custodian-a","custodian-b","custodian-c")}
        self.trust={"schema":"palaco.go20-checkpoint-custodian-trust.v1","members":{}}
        for mid,key in self.secrets.items():
            self.trust["members"][mid]={
                "public_key_hex":key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex(),
                "organization_id":"org-"+mid,"domain_id":"domain-"+mid,"status":"active"}
        self.pin={"schema":PIN_SCHEMA,"chain_sha256":canonical_hash(b.chain),
                  "trust_sha256":canonical_hash(self.trust),
                  "minimum_custodians":2,"minimum_sequence":44,
                  "minimum_retained_checkpoints":2}
        self.archive={"schema":SCHEMA,"copies":[]}
        for mid in ("custodian-a","custodian-b"):
            self.archive["copies"].append({"custodian_id":mid,
                "chain":copy.deepcopy(b.chain),"signature_ed25519_hex":self.sign(mid)})
    def sign(self,mid):
        b=self.b
        statement={"schema":STATEMENT_SCHEMA,"repository":"Maurits-pixe/PALACO",
          "chain_sha256":canonical_hash(b.chain),
          "first_sequence":b.pin["first_sequence"],"last_sequence":b.pin["last_sequence"],
          "trust_sha256":canonical_hash(self.trust),
          "custodian_id":mid,"decision":"HOLD","authorization":"DENY"}
        return self.secrets[mid].sign(bytes.fromhex(canonical_hash(statement))).hex()
    def check(self):
        b=self.b
        return assess(b.chain,b.pin,b.trust,b.v45,self.archive,self.trust,self.pin)
    def test_two_valid_copies_still_hold_deny(self):
        v=self.check()
        self.assertTrue(v["custody_evidence_valid"],v["errors"])
        self.assertEqual(v["checkpoints_archived"],2)
        self.assertEqual(v["custodians_verified"],2)
        for k in ("physical_availability_verified","restoration_performed",
          "missing_witness_quorum_overridden","checkpoint_published","failover_authorized",
          "production_commit_performed"):
            self.assertFalse(v[k])
    def test_one_archive_absent(self):
        self.archive["copies"].pop()
        self.assertIn("invalid_archived_copies",self.check()["errors"])
    def test_tampered_archived_checkpoint(self):
        self.archive["copies"][1]["chain"]["entries"][0]["checkpoint"]["sequence"]=88
        self.assertIn("missing_or_divergent_archive:1",self.check()["errors"])
    def test_forged_custody_signature(self):
        self.archive["copies"][0]["signature_ed25519_hex"]="0"*128
        self.assertIn("invalid_custody_signature:0",self.check()["errors"])
    def test_duplicate_custodian(self):
        self.archive["copies"][1]["custodian_id"]="custodian-a"
        self.assertIn("missing_or_duplicate_custodian:1",self.check()["errors"])
    def test_revoked_custodian(self):
        self.trust["members"]["custodian-b"]["status"]="revoked"
        self.pin["trust_sha256"]=canonical_hash(self.trust)
        self.assertFalse(self.check()["custody_evidence_valid"])
    def test_shared_custody_organization(self):
        self.trust["members"]["custodian-b"]["organization_id"]="org-custodian-a"
        self.pin["trust_sha256"]=canonical_hash(self.trust)
        self.assertIn("overlapping_custody:1",self.check()["errors"])
    def test_shared_custody_domain(self):
        self.trust["members"]["custodian-b"]["domain_id"]="domain-custodian-a"
        self.pin["trust_sha256"]=canonical_hash(self.trust)
        self.assertIn("overlapping_custody:1",self.check()["errors"])
    def test_changed_key_registry_not_anchored(self):
        self.trust["members"]["custodian-b"]["domain_id"]="forged"
        self.assertIn("custodian_trust_anchor_mismatch",self.check()["errors"])
    def test_expired_retention_floor(self):
        self.pin["minimum_retained_checkpoints"]=3
        self.assertIn("retention_floor_or_sequence_rollback",self.check()["errors"])
    def test_rollback_sequence(self):
        self.pin["minimum_sequence"]=45
        self.assertIn("retention_floor_or_sequence_rollback",self.check()["errors"])
    def test_tampered_pinned_chain(self):
        self.pin["chain_sha256"]="f"*64
        self.assertIn("archive_chain_anchor_mismatch",self.check()["errors"])
    def test_underlying_v46_missing_receipt_not_recovered_by_archives(self):
        self.b.chain["entries"][0]["receipts"].pop()
        self.pin["chain_sha256"]=canonical_hash(self.b.chain)
        self.assertTrue(any(e.startswith("v46:") for e in self.check()["errors"]))
    def test_underlying_v45_fork_not_recovered_by_archives(self):
        self.b.base.base.fork_with_valid_alternative_votes()
        self.assertTrue(any(e.startswith("v46:") for e in self.check()["errors"]))
    def test_archived_copy_missing_checkpoint(self):
        self.archive["copies"][0]["chain"]["entries"].pop()
        self.assertFalse(self.check()["custody_evidence_valid"])
    def test_signature_replay_from_other_custodian(self):
        self.archive["copies"][1]["signature_ed25519_hex"]=self.archive["copies"][0]["signature_ed25519_hex"]
        self.assertIn("invalid_custody_signature:1",self.check()["errors"])
    def test_boolean_retention_floor(self):
        self.pin["minimum_retained_checkpoints"]=True
        self.assertIn("invalid_retention_pin",self.check()["errors"])
    def test_invalid_quorum_count(self):
        self.pin["minimum_custodians"]=4
        self.assertIn("invalid_retention_pin",self.check()["errors"])
    def test_unknown_custodian(self):
        self.archive["copies"][0]["custodian_id"]="unknown"
        self.assertFalse(self.check()["custody_evidence_valid"])
    def test_revised_archive_pin_cannot_waive_quorum(self):
        self.b.chain["entries"][1]["receipts"][0]["signature_ed25519_hex"]="0"*128
        self.pin["chain_sha256"]=canonical_hash(self.b.chain)
        self.assertFalse(self.check()["custody_evidence_valid"])

if __name__=="__main__":
    unittest.main()
