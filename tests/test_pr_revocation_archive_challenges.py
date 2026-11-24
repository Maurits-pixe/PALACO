"""GO-20 v57: historical archive retrieval challenge security regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pr_audit_integrity import canonical_hash
from pr_revocation_archive_challenges import SCHEMA, PIN_SCHEMA, RESPONSE_SCHEMA, assess
from test_pr_revocation_checkpoint_receipts import RevocationReceiptTests


class InvalidArchiveChallengeTests(unittest.TestCase):
    def test_missing_sources_hold_deny(self):
        out = assess(None, None, None, None)
        self.assertFalse(out["challenge_evidence_valid"])
        self.assertEqual((out["decision"], out["authorization"]), ("HOLD", "DENY"))


class ArchiveChallengeTests(unittest.TestCase):
    def setUp(self):
        base = RevocationReceiptTests("test_valid_archived_claims_still_deny")
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        self.sources = {
            "v55_sources": base.sources, "custody": base.custody,
            "trust": base.trust, "independent_pin": base.pin,
        }
        self.pin = {
            "schema": PIN_SCHEMA,
            "v56_custody_sha256": canonical_hash(base.custody),
            "trust_sha256": canonical_hash(base.trust),
            "challenges_sha256": "0" * 64,
            "minimum_epoch": 21, "minimum_responses": 2,
        }
        self.challenges = {"schema": SCHEMA, "epochs": []}
        for i, item in enumerate(base.custody["epochs"]):
            challenge = {
                "epoch": item["epoch"], "nonce_sha256": format(i + 1, "064x"),
                "issued_at": 100, "expires_at": 150, "responses": [],
            }
            for cid in ("archive-a", "archive-b"):
                challenge["responses"].append(self.respond(challenge, cid, item))
            self.challenges["epochs"].append(challenge)
        self.repin()

    def respond(self, challenge, cid, item):
        digest = canonical_hash(item["checkpoint"])
        statement = {
            "schema": RESPONSE_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "epoch": challenge["epoch"],
            "nonce_sha256": challenge["nonce_sha256"],
            "issued_at": challenge["issued_at"], "expires_at": challenge["expires_at"],
            "checkpoint_sha256": digest, "retrieved_sha256": digest,
            "custodian_id": cid,
            "trust_sha256": self.pin["trust_sha256"],
            "v56_custody_sha256": self.pin["v56_custody_sha256"],
            "decision": "HOLD", "authorization": "DENY",
        }
        return {
            "custodian_id": cid, "checkpoint_sha256": digest,
            "nonce_sha256": challenge["nonce_sha256"],
            "retrieved_sha256": digest,
            "signature_ed25519_hex": self.base.secret[cid].sign(
                bytes.fromhex(canonical_hash(statement))).hex(),
        }

    def repin(self):
        self.pin["challenges_sha256"] = canonical_hash(self.challenges)

    def check(self, observed_at=120):
        return assess(self.sources, self.challenges, self.pin, observed_at)

    def test_complete_claims_still_hold_deny(self):
        v = self.check()
        self.assertTrue(v["challenge_evidence_valid"], v["errors"])
        self.assertEqual((v["epochs_verified"], v["responses_verified"]), (2, 4))
        for field in ("remote_availability_verified", "historical_recovery_performed",
                      "trusted_time_verified", "one_time_nonce_enforced",
                      "missing_history_recovered", "merge_authorized",
                      "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[field])

    def test_missing_epoch(self):
        self.challenges["epochs"].pop()
        self.repin()
        self.assertIn("invalid_challenge_bundle", self.check()["errors"])

    def test_nonce_reused_across_epochs(self):
        self.challenges["epochs"][1]["nonce_sha256"] = self.challenges["epochs"][0]["nonce_sha256"]
        self.repin()
        self.assertIn("invalid_stale_or_reused_challenge:1", self.check()["errors"])

    def test_expired_challenge(self):
        self.assertIn("invalid_stale_or_reused_challenge:0", self.check(151)["errors"])

    def test_future_challenge(self):
        self.assertIn("invalid_stale_or_reused_challenge:0", self.check(99)["errors"])

    def test_forged_response(self):
        self.challenges["epochs"][0]["responses"][0]["signature_ed25519_hex"] = "0" * 128
        self.repin()
        self.assertIn("invalid_retrieval_signature:0:archive-a", self.check()["errors"])

    def test_stale_response_nonce(self):
        self.challenges["epochs"][0]["responses"][0]["nonce_sha256"] = "a" * 64
        self.repin()
        self.assertIn("stale_or_corrupt_retrieval_claim:0:archive-a", self.check()["errors"])

    def test_wrong_retrieval_digest(self):
        self.challenges["epochs"][1]["responses"][0]["retrieved_sha256"] = "b" * 64
        self.repin()
        self.assertIn("stale_or_corrupt_retrieval_claim:1:archive-a", self.check()["errors"])

    def test_wrong_checkpoint_digest(self):
        self.challenges["epochs"][0]["responses"][0]["checkpoint_sha256"] = "c" * 64
        self.repin()
        self.assertFalse(self.check()["challenge_evidence_valid"])

    def test_signature_replayed_across_epochs(self):
        self.challenges["epochs"][1]["responses"][0]["signature_ed25519_hex"] = (
            self.challenges["epochs"][0]["responses"][0]["signature_ed25519_hex"])
        self.repin()
        self.assertIn("invalid_retrieval_signature:1:archive-a", self.check()["errors"])

    def test_duplicate_responder(self):
        self.challenges["epochs"][0]["responses"][1] = copy.deepcopy(
            self.challenges["epochs"][0]["responses"][0])
        self.repin()
        self.assertIn("unrecognized_or_duplicate_response:0:1", self.check()["errors"])

    def test_unarchived_responder(self):
        c = self.challenges["epochs"][0]
        c["responses"][1] = self.respond(c, "archive-c", self.base.custody["epochs"][0])
        self.repin()
        self.assertIn("unrecognized_or_duplicate_response:0:1", self.check()["errors"])

    def test_quorum_raised(self):
        self.pin["minimum_responses"] = 3
        self.assertIn("insufficient_retrieval_response_quorum:0", self.check()["errors"])

    def test_boolean_observed_time(self):
        self.assertIn("invalid_observation_time", self.check(True)["errors"])

    def test_boolean_quorum(self):
        self.pin["minimum_responses"] = True
        self.assertIn("invalid_external_challenge_pin", self.check()["errors"])

    def test_external_pin_tampered(self):
        self.pin["v56_custody_sha256"] = "f" * 64
        self.assertIn("independent_challenge_anchor_mismatch", self.check()["errors"])

    def test_original_v56_signature_missing(self):
        self.base.custody["epochs"][0]["receipts"][0]["signature_ed25519_hex"] = "0"*128
        self.pin["v56_custody_sha256"] = canonical_hash(self.base.custody)
        self.repin()
        self.assertTrue(any(x.startswith("v56:") for x in self.check()["errors"]))

    def test_unknown_custodian_registry_substitution(self):
        self.base.trust["custodians"]["archive-b"]["public_key_hex"] = "f" * 64
        self.assertFalse(self.check()["challenge_evidence_valid"])

    def test_old_epoch_floor(self):
        self.pin["minimum_epoch"] = 22
        self.assertIn("epoch_rollback_or_incomplete_challenges", self.check()["errors"])

    def test_unpinned_response_mutation(self):
        self.challenges["epochs"][0]["responses"].pop()
        self.assertIn("independent_challenge_anchor_mismatch", self.check()["errors"])

    def test_long_interval_rejected(self):
        self.challenges["epochs"][0]["expires_at"] = 4000
        self.repin()
        self.assertIn("invalid_stale_or_reused_challenge:0", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
