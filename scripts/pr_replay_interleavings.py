#!/usr/bin/env python3
"""GO-20 v9 deterministic in-memory interleaving / rollback test oracle.

No database or external storage. A successful simulated commit conveys NO
authority: GO-13 HOLD and authorization DENY remain unconditional.
"""
from __future__ import annotations

import copy
from pr_attestation_chain import digest
from pr_replay_transaction_contract import evaluate_transition

FAULT_POINTS = frozenset({"before_cas", "after_validation", "before_commit"})


class SimulatedReplayStore:
    """Isolated state machine, not a substitute for database isolation."""

    def __init__(self, initial_state: dict):
        self._state = copy.deepcopy(initial_state)
        self._history = []

    def snapshot(self) -> dict:
        return copy.deepcopy(self._state)

    def history(self) -> list[dict]:
        return copy.deepcopy(self._history)

    def attempt(self, proposal: object, *, fault: str | None = None) -> dict:
        """Model one serialized commit decision and fault-induced rollback."""
        if fault is not None and fault not in FAULT_POINTS:
            return self._verdict(["unknown_fault_point"])
        if fault == "before_cas":
            return self._verdict(["fault_before_cas"])
        current = self.snapshot()
        result = evaluate_transition(current, proposal)
        if not result["preconditions_met"]:
            return self._verdict(result["errors"])
        if fault == "after_validation":
            return self._verdict(["fault_after_validation"])
        candidate = result["proposed_next_state"]
        if candidate is None:
            return self._verdict(["missing_candidate"])
        if fault == "before_commit":
            return self._verdict(["fault_before_commit"])
        # This assignment is the ONLY state change in the simulation; a real
        # implementation must use a serializable DB transaction instead.
        self._state = copy.deepcopy(candidate)
        receipt = {
            "schema": "palaco.pr-simulated-replay-receipt.v1",
            "revision": self._state["revision"],
            "state_sha256": digest(self._state),
            "simulated_only": True,
        }
        self._history.append(receipt)
        return self._verdict([], simulated_receipt=receipt)

    @staticmethod
    def _verdict(errors: list[str], simulated_receipt: dict | None = None) -> dict:
        return {
            "schema": "palaco.pr-simulated-cas-verdict.v1",
            "simulation_accepted": simulated_receipt is not None,
            "errors": sorted(set(errors)),
            "simulated_receipt": simulated_receipt,
            "database_commit_performed": False,
            "decision": "HOLD",
            "authorization": "DENY",
        }


def explore_two_orders(initial_state: dict, first: dict, second: dict) -> dict:
    """Exhaust the two serial orders of two precomputed competing proposals."""
    outcomes = []
    for order in ((first, second), (second, first)):
        store = SimulatedReplayStore(initial_state)
        attempts = [store.attempt(proposal) for proposal in order]
        outcomes.append({
            "accepted": sum(bool(item["simulation_accepted"]) for item in attempts),
            "errors": [item["errors"] for item in attempts],
            "final_revision": store.snapshot().get("revision"),
            "final_state_sha256": digest(store.snapshot()),
            "receipt_count": len(store.history()),
        })
    return {
        "schema": "palaco.pr-interleaving-review.v1",
        "outcomes": outcomes,
        "decision": "HOLD",
        "authorization": "DENY",
        "real_concurrency_exercised": False,
        "database_commit_performed": False,
    }
