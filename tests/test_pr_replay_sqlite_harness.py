"""GO-20 v10 disposable SQLite isolation, durability and rollback tests."""
import concurrent.futures
import importlib.util
import sys
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "pr_replay_sqlite_harness", SCRIPTS / "pr_replay_sqlite_harness.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from pr_attestation_chain import digest
from pr_replay_transaction_contract import JOURNAL_SCHEMA, PROPOSAL_SCHEMA, STATE_SCHEMA


class SQLiteIntegrationTests(unittest.TestCase):
    def state(self):
        return {"schema": STATE_SCHEMA, "revision": 0, "registry": {"test_only": True},
                "journal": {"schema": JOURNAL_SCHEMA, "consumed_entry_sha256": []}}

    def proposal(self, state, token):
        new_journal = {"schema": JOURNAL_SCHEMA, "consumed_entry_sha256":
                       sorted(state["journal"]["consumed_entry_sha256"] + [token])}
        proposal = {
            "schema": PROPOSAL_SCHEMA, "expected_revision": state["revision"],
            "expected_state_sha256": digest(state), "new_journal_sha256": digest(new_journal),
            "new_journal": new_journal, "entry_hashes": [token],
            "atomic_commit_performed": False,
        }
        proposal["proposal_sha256"] = digest(proposal)
        return proposal

    def test_commit_is_durable_across_connections(self):
        with module.DisposableSQLiteReplay(self.state()) as store:
            result = store.attempt(self.proposal(store.snapshot(), "a" * 64))
            self.assertTrue(result["test_transaction_committed"], result["errors"])
            self.assertEqual(store.snapshot()["revision"], 1)
            self.assertEqual(store.receipts(), ["a" * 64])
            self.assertEqual(result["authorization"], "DENY")
            self.assertFalse(result["production_database_touched"])

    def test_rollback_after_state_write(self):
        with module.DisposableSQLiteReplay(self.state()) as store:
            result = store.attempt(self.proposal(store.snapshot(), "a" * 64),
                                   fault="after_state_write")
            self.assertIn("injected_rollback", result["errors"])
            self.assertEqual(store.snapshot(), self.state())
            self.assertEqual(store.receipts(), [])

    def test_rollback_after_receipt_insert(self):
        with module.DisposableSQLiteReplay(self.state()) as store:
            result = store.attempt(self.proposal(store.snapshot(), "a" * 64),
                                   fault="after_receipts")
            self.assertIn("injected_rollback", result["errors"])
            self.assertEqual(store.snapshot(), self.state())
            self.assertEqual(store.receipts(), [])

    def test_competing_threads_only_one_commits(self):
        with module.DisposableSQLiteReplay(self.state()) as store:
            base = store.snapshot()
            proposals = [self.proposal(base, "a" * 64), self.proposal(base, "b" * 64)]
            barrier = threading.Barrier(2)

            def worker(candidate):
                barrier.wait(timeout=5)
                return store.attempt(candidate)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, p) for p in proposals]
                results = [f.result(timeout=15) for f in futures]
            self.assertEqual(sum(r["test_transaction_committed"] for r in results), 1)
            self.assertEqual(store.snapshot()["revision"], 1)
            self.assertEqual(len(store.receipts()), 1)
            self.assertTrue(all(r["authorization"] == "DENY" for r in results))

    def test_same_token_cannot_be_reused(self):
        with module.DisposableSQLiteReplay(self.state()) as store:
            proposal = self.proposal(store.snapshot(), "a" * 64)
            self.assertTrue(store.attempt(proposal)["test_transaction_committed"])
            second = store.attempt(proposal)
            self.assertFalse(second["test_transaction_committed"])
            self.assertEqual(len(store.receipts()), 1)

    def test_bad_proposal_does_not_commit(self):
        with module.DisposableSQLiteReplay(self.state()) as store:
            candidate = self.proposal(store.snapshot(), "a" * 64)
            candidate["expected_revision"] = 99
            result = store.attempt(candidate)
            self.assertFalse(result["test_transaction_committed"])
            self.assertEqual(store.snapshot()["revision"], 0)

    def test_rollback_then_retry_commits_once(self):
        with module.DisposableSQLiteReplay(self.state()) as store:
            proposal = self.proposal(store.snapshot(), "a" * 64)
            self.assertFalse(store.attempt(proposal, fault="after_receipts")["test_transaction_committed"])
            self.assertTrue(store.attempt(proposal)["test_transaction_committed"])
            self.assertEqual(store.receipts(), ["a" * 64])

    def test_closed_fixture_rejects_work(self):
        store = module.DisposableSQLiteReplay(self.state())
        proposal = self.proposal(store.snapshot(), "a" * 64)
        store.close()
        outcome = store.attempt(proposal)
        self.assertIn("fixture_closed", outcome["errors"])
        self.assertEqual(outcome["authorization"], "DENY")


if __name__ == "__main__":
    unittest.main()
