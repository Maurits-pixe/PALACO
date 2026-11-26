#!/usr/bin/env python3
"""GO-20 v41: offline split-brain and fenced-handoff evidence assessment.

Only verifies externally supplied transition evidence and full v40 snapshot
equality. NEVER issues a fence, promotes a node, writes, or grants authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_recovery_handoff import verify as verify_handoff, canonical, digest

SCHEMA = "palaco.go20-recovery-fencing-evidence.v1"
PIN_SCHEMA = "palaco.go20-recovery-fencing-pin.v1"
RESULT_SCHEMA = "palaco.go20-recovery-fencing-verdict.v1"


def verdict(errors, epochs=0, records=0):
    return {
        "schema": RESULT_SCHEMA,
        "fencing_evidence_valid": not errors,
        "epochs_checked": epochs,
        "records_verified": records,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "fence_performed": False,
        "failover_authorized": False,
        "promotion_performed": False,
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def check(primary, candidate, handoff_pin, transition, external_pin):
    try:
        if (not isinstance(transition, dict) or set(transition) != {
                "schema", "repository", "previous_epoch", "candidate_epoch",
                "old_writer_id", "candidate_id", "node_roles",
                "fencing_ack", "handoff_sha256"
        } or transition["schema"] != SCHEMA or
                transition["repository"] != "Maurits-pixe/PALACO"):
            return verdict(["invalid_transition"])
        if (not isinstance(external_pin, dict) or set(external_pin) != {
                "schema", "transition_sha256", "minimum_epoch",
                "expected_previous_writer", "expected_candidate"
        } or external_pin["schema"] != PIN_SCHEMA or
                type(external_pin["minimum_epoch"]) is not int or
                external_pin["minimum_epoch"] < 0):
            return verdict(["invalid_independent_transition_pin"])
        old = transition["previous_epoch"]
        new = transition["candidate_epoch"]
        if (type(old) is not int or old < 0 or type(new) is not int or
                new != old + 1 or new < external_pin["minimum_epoch"]):
            return verdict(["epoch_rollback_or_gap"])
        if (not isinstance(transition["old_writer_id"], str) or
                not isinstance(transition["candidate_id"], str) or
                not transition["old_writer_id"] or
                not transition["candidate_id"] or
                transition["old_writer_id"] == transition["candidate_id"] or
                transition["old_writer_id"] != external_pin["expected_previous_writer"] or
                transition["candidate_id"] != external_pin["expected_candidate"]):
            return verdict(["writer_identity_conflict"])
        roles = transition["node_roles"]
        if (not isinstance(roles, dict) or set(roles) != {
                transition["old_writer_id"], transition["candidate_id"]
        } or roles.get(transition["old_writer_id"]) != "fenced" or
                roles.get(transition["candidate_id"]) != "candidate"):
            return verdict(["split_brain_or_unfenced_writer"])
        ack = transition["fencing_ack"]
        if (not isinstance(ack, dict) or set(ack) != {
                "fenced_node_id", "fenced_at_epoch", "acknowledged", "control_domain"
        } or ack["fenced_node_id"] != transition["old_writer_id"] or
                type(ack["fenced_at_epoch"]) is not int or
                ack["fenced_at_epoch"] != new or
                ack["acknowledged"] is not True or
                not isinstance(ack["control_domain"], str) or
                not ack["control_domain"]):
            return verdict(["fencing_ack_missing_or_invalid"])
        if not isinstance(transition["handoff_sha256"], str):
            return verdict(["invalid_handoff_hash"])
        from pr_audit_integrity import canonical_hash, is_hex
        if (not is_hex(external_pin["transition_sha256"], 64) or
                canonical_hash(transition) != external_pin["transition_sha256"]):
            return verdict(["independent_fencing_anchor_mismatch"])
        handoff = verify_handoff(primary, candidate, handoff_pin)
        if not handoff["handoff_consistent"]:
            return verdict(["handoff:" + e for e in handoff["errors"]])
        snapshot_digest = digest(canonical(primary))
        if transition["handoff_sha256"] != snapshot_digest:
            return verdict(["handoff_binding_mismatch"])
        # Technical approval of evidence is NOT authorization of a transition.
        return verdict([], 2, handoff["rows_compared"])
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            OverflowError, MemoryError, RecursionError) as exc:
        return verdict(["malformed_fencing_evidence:" + type(exc).__name__])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("primary", "candidate", "handoff-pin", "transition", "independent-pin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        from pr_audit_integrity import unique_pairs
        def read(path):
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError("missing_or_oversize_evidence")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        result = check(read(args.primary), read(args.candidate),
                       read(args.handoff_pin), read(args.transition),
                       read(args.independent_pin))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["fencing_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
