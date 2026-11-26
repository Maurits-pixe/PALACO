"""GO-20 v9 interleaving and fault rollback regression tests."""
import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("pr_replay_interleavings", ROOT / "scripts" / "pr_replay_interleavings.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from pr_attestation_chain import digest
from pr_replay_transaction_contract import JOURNAL_SCHEMA, PROPOSAL_SCHEMA, STATE_SCHEMA


class InterleavingTests(unittest.TestCase):
    def setup_state(self):
        return {"schema": STATE_SCHEMA, "revision": 12, "registry": {"demo": True},
                "journal": {"schema": JOURNAL_SCHEMA, "consumed_entry_sha256": []}}

    def proposal(self, state, hashes):
        new_journal = {"schema": JOURNAL_SCHEMA, "consumed_entry_sha256": sorted(
            state["journal"]["consumed_entry_sha256"] + hashes)}
        value = {"schema": PROPOSAL_SCHEMA, "expected_revision": state["revision"],
                 "expected_state_sha256": digest(state), "new_journal_sha256": digest(new_journal),
                 "new_journal": new_journal, "entry_hashes": hashes,
                 "atomic_commit_performed": False}
        value["proposal_sha256"] = digest(value)
        return value

    def test_two_competing_proposals_one_winner_in_both_orders(self):
        state = self.setup_state()
        a, b = self.proposal(state, ["a" * 64]), self.proposal(state, ["b" * 64])
        outcomes = module.explore_two_orders(state, a, b)
        self.assertEqual([item["accepted"] for item in outcomes["outcomes"]], [1, 1])
        self.assertEqual([item["receipt_count"] for item in outcomes["outcomes"]], [1, 1])
        self.assertEqual([item["final_revision"] for item in outcomes["outcomes"]], [13, 13])
        self.assertFalse(outcomes["real_concurrency_exercised"])
        self.assertEqual(outcomes["authorization"], "DENY")

    def test_same_replay_token_cannot_be_consumed_twice(self):
        state = self.setup_state()
        proposal = self.proposal(state, ["a" * 64])
        store = module.SimulatedReplayStore(state)
        first, second = store.attempt(proposal), store.attempt(proposal)
        self.assertTrue(first["simulation_accepted"])
        self.assertFalse(second["simulation_accepted"])
        self.assertEqual(len(store.history()), 1)
        self.assertEqual(second["authorization"], "DENY")

    def test_all_fault_points_roll_back_without_receipt(self):
        for point in module.FAULT_POINTS:
            with self.subTest(point=point):
                state = self.setup_state()
                original = copy.deepcopy(state)
                store = module.SimulatedReplayStore(state)
                result = store.attempt(self.proposal(state, ["a" * 64]), fault=point)
                self.assertFalse(result["simulation_accepted"])
                self.assertIsNone(result["simulated_receipt"])
                self.assertEqual(store.snapshot(), original)
                self.assertEqual(store.history(), [])

    def test_snapshot_mutations_do_not_change_store(self):
        state = self.setup_state()
        store = module.SimulatedReplayStore(state)
        state["revision"] = 77
        snapshot = store.snapshot()
        snapshot["revision"] = 88
        self.assertEqual(store.snapshot()["revision"], 12)

    def test_stale_proposal_is_rejected_without_revision_change(self):
        state = self.setup_state()
        store = module.SimulatedReplayStore(state)
        other = self.proposal(state, ["b" * 64])
        store.attempt(self.proposal(state, ["a" * 64]))
        prior = store.snapshot()
        result = store.attempt(other)
        self.assertFalse(result["simulation_accepted"])
        self.assertIn("revision_conflict", result["errors"])
        self.assertEqual(store.snapshot(), prior)

    def test_invalid_fault_point_does_not_mutate(self):
        state = self.setup_state()
        store = module.SimulatedReplayStore(state)
        verdict = store.attempt(self.proposal(state, ["a" * 64]), fault="commit_anyway")
        self.assertIn("unknown_fault_point", verdict["errors"])
        self.assertEqual(store.snapshot(), state)

    def test_fault_after_success_does_not_create_second_receipt(self):
        state = self.setup_state()
        store = module.SimulatedReplayStore(state)
        store.attempt(self.proposal(state, ["a" * 64]))
        after = store.snapshot()
        result = store.attempt(self.proposal(after, ["b" * 64]), fault="before_commit")
        self.assertFalse(result["simulation_accepted"])
        self.assertEqual(len(store.history()), 1)
        self.assertEqual(store.snapshot(), after)

    def test_all_results_are_hold_deny(self):
        state = self.setup_state()
        store = module.SimulatedReplayStore(state)
        proposal = self.proposal(state, ["a" * 64])
        for result in (store.attempt(proposal, fault="before_cas"), store.attempt(proposal),
                       store.attempt(proposal)):
            self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))
            self.assertFalse(result["database_commit_performed"])


if __name__ == "__main__":
    unittest.main()
