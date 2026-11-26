"""GO-20 v48: offline challenge response security regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_audit_integrity import canonical_hash
from pr_archive_availability_challenge import SCHEMA, PIN_SCHEMA, RESPONSE_SCHEMA, assess
from test_pr_checkpoint_retention_custody import CustodyTests


class InvalidChallengeTests(unittest.TestCase):
    def test_missing_evidence_denied(self):
        r = assess(*([None] * 10))
        self.assertFalse(r["challenge_evidence_valid"])
        self.assertEqual((r["decision"], r["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(r["remote_availability_verified"])


class ChallengeTests(unittest.TestCase):
    def setUp(self):
        source = CustodyTests("test_two_valid_copies_still_hold_deny")
        source.setUp()
        self.source = source
        b = source.b
        self.challenge = {
            "schema": SCHEMA, "nonce_sha256": "e" * 64,
            "chain_sha256": canonical_hash(b.chain),
            "sequence": b.pin["last_sequence"], "minimum_response_count": 2,
        }
        self.pin = {
            "schema": PIN_SCHEMA,
            "challenge_sha256": canonical_hash(self.challenge),
            "trusted_chain_sha256": canonical_hash(b.chain),
            "minimum_sequence": b.pin["last_sequence"],
            "minimum_responses": 2,
        }
        self.responses = {
            "schema": "palaco.go20-archive-availability-responses.v1",
            "entries": [],
        }
        for mid in ("custodian-a", "custodian-b"):
            self.responses["entries"].append(self.response(mid))

    def response(self, mid):
        b = self.source.b
        statement = {
            "schema": RESPONSE_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "custodian_id": mid, "nonce_sha256": self.challenge["nonce_sha256"],
            "chain_sha256": self.challenge["chain_sha256"],
            "sequence": self.challenge["sequence"],
            "trust_sha256": canonical_hash(self.source.trust),
            "decision": "HOLD", "authorization": "DENY",
        }
        return {
            "custodian_id": mid,
            "nonce_sha256": self.challenge["nonce_sha256"],
            "chain_sha256": self.challenge["chain_sha256"],
            "sequence": self.challenge["sequence"],
            "signature_ed25519_hex": self.source.secrets[mid].sign(
                bytes.fromhex(canonical_hash(statement))).hex(),
        }

    def check(self):
        s = self.source
        return assess(s.b.chain, s.b.pin, s.b.trust, s.b.v45,
                      s.archive, s.trust, s.pin, self.challenge, self.responses, self.pin)

    def test_valid_response_evidence_remains_deny(self):
        r = self.check()
        self.assertTrue(r["challenge_evidence_valid"], r["errors"])
        self.assertEqual(r["responses_verified"], 2)
        for field in ("remote_availability_verified", "restoration_performed",
                      "challenge_freshness_independently_verified",
                      "missing_witness_quorum_overridden", "failover_authorized",
                      "checkpoint_published", "production_commit_performed"):
            self.assertFalse(r[field])

    def test_nonce_replaced_in_response(self):
        self.responses["entries"][0]["nonce_sha256"] = "f" * 64
        self.assertIn("stale_or_mismatched_response:0", self.check()["errors"])

    def test_wrong_sequence(self):
        self.responses["entries"][1]["sequence"] -= 1
        self.assertIn("stale_or_mismatched_response:1", self.check()["errors"])

    def test_old_challenge_replayed(self):
        self.challenge["nonce_sha256"] = "f" * 64
        self.pin["challenge_sha256"] = canonical_hash(self.challenge)
        self.assertFalse(self.check()["challenge_evidence_valid"])

    def test_unpinned_challenge(self):
        self.challenge["nonce_sha256"] = "f" * 64
        self.assertIn("challenge_anchor_mismatch", self.check()["errors"])

    def test_forged_custodian_signature(self):
        self.responses["entries"][0]["signature_ed25519_hex"] = "0" * 128
        self.assertIn("invalid_challenge_signature:0", self.check()["errors"])

    def test_response_signature_copied(self):
        self.responses["entries"][1]["signature_ed25519_hex"] = (
            self.responses["entries"][0]["signature_ed25519_hex"])
        self.assertIn("invalid_challenge_signature:1", self.check()["errors"])

    def test_duplicate_response(self):
        self.responses["entries"][1] = copy.deepcopy(self.responses["entries"][0])
        self.assertIn("unknown_duplicate_or_unarchived_custodian:1", self.check()["errors"])

    def test_response_from_non_archived_member(self):
        self.responses["entries"][1] = self.response("custodian-c")
        self.assertIn("unknown_duplicate_or_unarchived_custodian:1", self.check()["errors"])

    def test_response_quorum_too_high(self):
        self.pin["minimum_responses"] = 3
        self.assertIn("challenge_response_quorum_not_met", self.check()["errors"])

    def test_challenge_quorum_too_high(self):
        self.challenge["minimum_response_count"] = 4
        self.pin["challenge_sha256"] = canonical_hash(self.challenge)
        self.assertIn("unachievable_response_quorum", self.check()["errors"])

    def test_boolean_quorum_denied(self):
        self.pin["minimum_responses"] = True
        self.assertIn("invalid_challenge_pin", self.check()["errors"])

    def test_minimum_sequence_rollback(self):
        self.pin["minimum_sequence"] += 1
        self.assertIn("stale_or_unpinned_sequence", self.check()["errors"])

    def test_trust_anchor_changed(self):
        self.source.trust["members"]["custodian-a"]["domain_id"] = "changed"
        self.assertFalse(self.check()["challenge_evidence_valid"])

    def test_underlying_v47_failure_cannot_be_overridden(self):
        self.source.b.chain["entries"][0]["receipts"].pop()
        self.source.pin["chain_sha256"] = canonical_hash(self.source.b.chain)
        self.challenge["chain_sha256"] = canonical_hash(self.source.b.chain)
        self.pin["trusted_chain_sha256"] = canonical_hash(self.source.b.chain)
        self.pin["challenge_sha256"] = canonical_hash(self.challenge)
        self.assertTrue(any(e.startswith("v47:") for e in self.check()["errors"]))

    def test_archive_data_missing(self):
        self.source.archive["copies"].pop()
        self.assertTrue(any(e.startswith("v47:") for e in self.check()["errors"]))

    def test_wrong_chain_hash_in_response(self):
        self.responses["entries"][0]["chain_sha256"] = "b" * 64
        self.assertIn("stale_or_mismatched_response:0", self.check()["errors"])

    def test_response_does_not_have_authority(self):
        r = self.check()
        self.assertFalse(r["release_authorized"])
        self.assertFalse(r["merge_authorized"])
        self.assertFalse(r["deployment_authorized"])


if __name__ == "__main__":
    unittest.main()
