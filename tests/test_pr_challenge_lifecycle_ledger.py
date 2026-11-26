"""GO-20 v49: durable SQLite test-ledger lifecycle and concurrent replay tests."""
import copy
import tempfile
import threading
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_challenge_lifecycle_ledger import ChallengeLedger
from pr_audit_integrity import canonical_hash
from test_pr_archive_availability_challenge import ChallengeTests


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "v49-test-ledger.sqlite3"
        self.ledger = ChallengeLedger(self.path)
        self.v48 = ChallengeTests("test_valid_response_evidence_remains_deny")
        self.v48.setUp()
        self.challenge = self.v48.challenge
        self.pin = self.v48.pin
        s = self.v48.source
        self.sources = {
            "chain": s.b.chain,
            "chain_pin": s.b.pin,
            "witnesses": s.b.trust,
            "v45": s.b.v45,
            "archive": s.archive,
            "custodians": s.trust,
            "retention_pin": s.pin,
            "responses": self.v48.responses,
        }

    def issue(self, start=100, end=150, now=100):
        return self.ledger.issue(self.challenge, self.pin, start, end, now)

    def consume(self, now=105):
        return self.ledger.consume(self.challenge, self.pin, self.sources, now)

    def test_issue_and_verified_consume(self):
        self.assertEqual(self.issue()["status"], "ISSUED_TEST_ONLY")
        r = self.consume()
        self.assertEqual(r["status"], "CONSUMED_TEST_ONLY", r["errors"])
        self.assertEqual(self.ledger.inspect(self.challenge["nonce_sha256"]), ("CONSUMED",100,150,105))
        self.assertEqual((r["decision"],r["authorization"]),("HOLD","DENY"))
        self.assertFalse(r["production_commit_performed"])

    def test_same_nonce_cannot_be_issued_twice(self):
        self.issue()
        self.assertIn("duplicate_nonce_or_challenge", self.issue()["errors"])

    def test_second_consume_is_replay(self):
        self.issue()
        self.consume()
        self.assertIn("challenge_already_consumed", self.consume()["errors"])

    def test_persists_across_new_connection(self):
        self.issue()
        new = ChallengeLedger(self.path)
        self.assertEqual(new.inspect(self.challenge["nonce_sha256"])[0], "ISSUED")
        self.assertEqual(new.consume(self.challenge,self.pin,self.sources,105)["status"],"CONSUMED_TEST_ONLY")

    def test_never_issued_denied(self):
        self.assertIn("challenge_not_issued", self.consume()["errors"])

    def test_expired_consume_denied(self):
        self.issue()
        self.assertIn("challenge_expired_or_clock_rollback",self.consume(150)["errors"])
        self.assertEqual(self.ledger.inspect(self.challenge["nonce_sha256"])[0],"ISSUED")

    def test_clock_rollback_denied(self):
        self.issue()
        self.assertIn("challenge_expired_or_clock_rollback",self.consume(99)["errors"])

    def test_expired_issue_denied(self):
        self.assertIn("invalid_or_expired_issue", self.issue(end=100)["errors"])

    def test_future_issue_without_matching_now_denied(self):
        self.assertIn("invalid_or_expired_issue",self.issue(start=101)["errors"])

    def test_unbounded_expiry_denied(self):
        self.assertIn("invalid_or_expired_issue",self.issue(end=5000)["errors"])

    def test_boolean_clock_denied(self):
        self.assertIn("invalid_or_expired_issue",self.issue(now=True)["errors"])

    def test_malformed_pin_denied(self):
        self.pin["challenge_sha256"]="0"*64
        self.assertIn("invalid_or_expired_issue",self.issue()["errors"])

    def test_reissued_nonce_with_changed_binding_denied(self):
        self.issue()
        self.challenge["sequence"]=45
        self.pin["challenge_sha256"]=canonical_hash(self.challenge)
        self.pin["minimum_sequence"]=45
        self.assertIn("nonce_reused_with_different_challenge",self.consume()["errors"])

    def test_forged_v48_signature_never_consumes(self):
        self.issue()
        self.v48.responses["entries"][0]["signature_ed25519_hex"]="0"*128
        self.assertIn("v48_evidence_invalid",self.consume()["errors"])
        self.assertEqual(self.ledger.inspect(self.challenge["nonce_sha256"])[0],"ISSUED")

    def test_missing_v48_archive_never_consumes(self):
        self.issue()
        self.sources["archive"]["copies"].pop()
        self.assertIn("v48_evidence_invalid",self.consume()["errors"])

    def test_invalid_source_shape_never_consumes(self):
        self.issue()
        self.sources.pop("responses")
        self.assertIn("invalid_consume_arguments",self.consume()["errors"])

    def test_concurrent_consume_at_most_once(self):
        self.issue()
        results=[]
        gate=threading.Barrier(8)
        def worker():
            gate.wait()
            results.append(self.consume()["status"])
        threads=[threading.Thread(target=worker) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=15)
        self.assertEqual(len(results),8)
        self.assertEqual(results.count("CONSUMED_TEST_ONLY"),1)
        self.assertEqual(results.count("DENIED"),7)

    def test_concurrent_issue_at_most_once(self):
        results=[]
        gate=threading.Barrier(8)
        def worker():
            gate.wait()
            results.append(self.issue()["status"])
        threads=[threading.Thread(target=worker) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=15)
        self.assertEqual(len(results),8)
        self.assertEqual(results.count("ISSUED_TEST_ONLY"),1)
        self.assertEqual(results.count("DENIED"),7)

    def test_no_global_or_inmemory_database(self):
        with self.assertRaises(ValueError):
            ChallengeLedger(":memory:")

    def test_consumed_row_cannot_be_reused_with_other_time(self):
        self.issue()
        self.consume()
        self.assertIn("challenge_already_consumed",self.consume(106)["errors"])


if __name__=="__main__":
    unittest.main()
