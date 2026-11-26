"""GO-20 v8: pure CAS / atomic replay transition negative tests."""
import copy
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "pr_replay_transaction_contract", SCRIPTS / "pr_replay_transaction_contract.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TransactionContractTests(unittest.TestCase):
    def fixture(self):
        current = {
            "schema": module.STATE_SCHEMA, "revision": 9,
            "registry": {"schema": "palaco.pr-trust-registry.v1", "keys": {"demo": "synthetic"}},
            "journal": {"schema": module.JOURNAL_SCHEMA, "consumed_entry_sha256": ["a" * 64]},
        }
        proposed = {"schema": module.JOURNAL_SCHEMA,
                    "consumed_entry_sha256": sorted(["a" * 64, "b" * 64])}
        proposal = {
            "schema": module.PROPOSAL_SCHEMA, "expected_revision": 9,
            "expected_state_sha256": module.digest(current),
            "new_journal_sha256": module.digest(proposed),
            "new_journal": proposed, "entry_hashes": ["b" * 64],
            "atomic_commit_performed": False,
        }
        proposal["proposal_sha256"] = module.digest(proposal)
        return current, proposal

    def test_successful_simulation_never_persists(self):
        current, proposal = self.fixture()
        initial = copy.deepcopy(current)
        result = module.evaluate_transition(current, proposal)
        self.assertTrue(result["preconditions_met"], result["errors"])
        self.assertEqual(result["proposed_next_state"]["revision"], 10)
        self.assertEqual(current, initial)
        self.assertFalse(result["state_persisted"])
        self.assertFalse(result["atomic_commit_performed"])
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))

    def test_stale_revision(self):
        state, proposal = self.fixture()
        state["revision"] = 10
        self.assertIn("revision_conflict", module.evaluate_transition(state, proposal)["errors"])

    def test_same_revision_but_different_state(self):
        state, proposal = self.fixture()
        state["registry"]["extra"] = "changed"
        self.assertIn("state_hash_conflict", module.evaluate_transition(state, proposal)["errors"])

    def test_replay_already_consumed(self):
        state, proposal = self.fixture()
        state["journal"]["consumed_entry_sha256"].append("b" * 64)
        self.assertIn("replay_conflict", module.evaluate_transition(state, proposal)["errors"])

    def test_proposal_digest_tampering(self):
        state, proposal = self.fixture()
        proposal["expected_revision"] = 8
        self.assertIn("proposal_digest_mismatch", module.evaluate_transition(state, proposal)["errors"])

    def test_unapproved_transition(self):
        state, proposal = self.fixture()
        proposal["new_journal"]["consumed_entry_sha256"] = ["b" * 64]
        self.assertIn("invalid_journal_transition", module.evaluate_transition(state, proposal)["errors"])

    def test_no_entries_to_consume(self):
        state, proposal = self.fixture()
        proposal["entry_hashes"] = []
        self.assertIn("invalid_journal_members", module.evaluate_transition(state, proposal)["errors"])

    def test_duplicate_entry_hashes(self):
        state, proposal = self.fixture()
        proposal["entry_hashes"] = ["b" * 64, "b" * 64]
        self.assertIn("invalid_journal_members", module.evaluate_transition(state, proposal)["errors"])

    def test_forged_commit_claim(self):
        state, proposal = self.fixture()
        proposal["atomic_commit_performed"] = True
        self.assertIn("invalid_commit_claim", module.evaluate_transition(state, proposal)["errors"])

    def test_missing_proposal(self):
        state, _ = self.fixture()
        result = module.evaluate_transition(state, None)
        self.assertFalse(result["preconditions_met"])
        self.assertEqual(result["authorization"], "DENY")

    def test_revision_type_rejected(self):
        state, proposal = self.fixture()
        state["revision"] = True
        self.assertIn("invalid_current_state", module.evaluate_transition(state, proposal)["errors"])

    def test_no_release_on_invalid_data(self):
        state, proposal = self.fixture()
        proposal["new_journal"]["consumed_entry_sha256"] = [None]
        result = module.evaluate_transition(state, proposal)
        self.assertFalse(result["preconditions_met"])
        self.assertIsNone(result["proposed_next_state"])
        self.assertEqual(result["authorization"], "DENY")


if __name__ == "__main__":
    unittest.main()
