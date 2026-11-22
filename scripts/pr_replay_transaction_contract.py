#!/usr/bin/env python3
"""PALACO GO-20 v8: pure, non-persistent atomic replay transition specification.

Simulates a single serializable compare-and-swap transaction over an immutable
state snapshot. This is a test oracle, NOT a database transaction or authority.
"""
from __future__ import annotations

import copy
from pr_attestation_chain import digest, is_hex

STATE_SCHEMA = "palaco.pr-signed-state.v1"
JOURNAL_SCHEMA = "palaco.pr-replay-journal.v1"
PROPOSAL_SCHEMA = "palaco.pr-replay-proposal.v1"
MAX_CONSUMED = 10000


def evaluate_transition(current: object, proposal: object) -> dict:
    """Return a candidate state only if ALL predicates hold, with no mutations."""
    errors: list[str] = []
    next_state = None
    if not isinstance(current, dict) or set(current) != {
        "schema", "revision", "registry", "journal"
    } or current.get("schema") != STATE_SCHEMA or type(current.get("revision")) is not int:
        errors.append("invalid_current_state")
    if not isinstance(proposal, dict) or set(proposal) != {
        "schema", "expected_revision", "expected_state_sha256",
        "new_journal_sha256", "new_journal", "entry_hashes",
        "atomic_commit_performed", "proposal_sha256",
    } or proposal.get("schema") != PROPOSAL_SCHEMA:
        errors.append("invalid_proposal")
    if errors:
        return _result(errors, None)

    try:
        if not is_hex(proposal["proposal_sha256"], 64) or digest({
            k: v for k, v in proposal.items() if k != "proposal_sha256"
        }) != proposal["proposal_sha256"]:
            errors.append("proposal_digest_mismatch")
        if proposal["atomic_commit_performed"] is not False:
            errors.append("invalid_commit_claim")
        revision = current["revision"]
        if revision < 0 or revision >= (2**63 - 1):
            errors.append("revision_out_of_range")
        if type(proposal["expected_revision"]) is not int or revision != proposal["expected_revision"]:
            errors.append("revision_conflict")
        if not is_hex(proposal["expected_state_sha256"], 64) or digest(current) != proposal["expected_state_sha256"]:
            errors.append("state_hash_conflict")

        journal = current["journal"]
        proposed = proposal["new_journal"]
        if (not isinstance(journal, dict) or set(journal) != {"schema", "consumed_entry_sha256"} or
                journal.get("schema") != JOURNAL_SCHEMA or
                not isinstance(proposed, dict) or set(proposed) != {"schema", "consumed_entry_sha256"} or
                proposed.get("schema") != JOURNAL_SCHEMA):
            errors.append("invalid_journal")
        else:
            old = journal["consumed_entry_sha256"]
            new = proposed["consumed_entry_sha256"]
            appended = proposal["entry_hashes"]
            if (not isinstance(old, list) or not isinstance(new, list) or
                    not isinstance(appended, list) or not appended or
                    len(old) > MAX_CONSUMED or len(new) > MAX_CONSUMED or
                    any(not is_hex(x, 64) for x in old + new + appended) or
                    len(set(old)) != len(old) or len(set(new)) != len(new) or
                    len(set(appended)) != len(appended)):
                errors.append("invalid_journal_members")
            else:
                if set(old).intersection(appended):
                    errors.append("replay_conflict")
                if new != sorted(old + appended):
                    errors.append("invalid_journal_transition")
                if digest(proposed) != proposal["new_journal_sha256"]:
                    errors.append("journal_digest_mismatch")
        if not errors:
            next_state = copy.deepcopy(current)
            next_state["revision"] = revision + 1
            next_state["journal"] = copy.deepcopy(proposed)
    except (TypeError, ValueError, OverflowError, RecursionError):
        errors.append("malformed_state_or_proposal")
    return _result(errors, next_state)


def _result(errors: list[str], state: dict | None) -> dict:
    return {
        "schema": "palaco.pr-replay-transition-verdict.v1",
        "preconditions_met": not errors,
        "errors": sorted(set(errors)),
        "proposed_next_state": state if not errors else None,
        "proposed_next_state_sha256": digest(state) if state is not None and not errors else None,
        "state_persisted": False,
        "atomic_commit_performed": False,
        "decision": "HOLD",
        "authorization": "DENY",
        "note": "Offline simulation only. No transaction, lock or receipt has been issued.",
    }
