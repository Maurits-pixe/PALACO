#!/usr/bin/env python3
"""GO-20 v63: offline archived-receipt succession and observer fork checks.

Reverify the complete v62 package in every chronology entry. Require a
strictly hash-linked sequence, independently pinned initial/final snapshots,
an unchanged custody key register, monotonic quorum and history floor, and
two matching observer views. No publication or live archive claims.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_head_succession_custody import assess as assess_v62

SCHEMA = "palaco.go20-head-custody-succession.v1"
PIN_SCHEMA = "palaco.go20-head-custody-succession-pin.v1"
HEAD_SCHEMA = "palaco.go20-head-custody-succession-independent-head.v1"
ZERO = "0" * 64
FIELDS = {"v61_sources", "copies", "trust", "independent_pin"}


def verdict(errors, verified=0):
    return {
        "schema": "palaco.go20-head-custody-succession-verdict.v1",
        "custody_succession_valid": not errors,
        "snapshots_verified": verified,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "remote_publication_verified": False, "storage_reachability_verified": False,
        "independent_media_custody_verified": False,
        "history_restored": False, "recovery_authorized": False,
        "failover_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def assess_view(view, pin):
    if (not isinstance(view, dict) or set(view) != {"schema", "snapshots"} or
            view.get("schema") != SCHEMA or
            not isinstance(view["snapshots"], list) or
            not 2 <= len(view["snapshots"]) <= 4):
        return ["invalid_custody_history"], 0
    if (not isinstance(pin, dict) or set(pin) != {
            "schema", "first_snapshot", "last_snapshot", "first_sha256",
            "last_sha256", "history_sha256", "v61_sources_sha256",
            "trust_sha256", "minimum_receipts", "minimum_round"
    } or pin.get("schema") != PIN_SCHEMA or
            any(type(pin.get(k)) is not int or pin[k] < bound for k, bound in (
                ("first_snapshot", 1), ("last_snapshot", 2),
                ("minimum_receipts", 2), ("minimum_round", 2))) or
            pin["last_snapshot"] != pin["first_snapshot"] + len(view["snapshots"]) - 1 or
            any(not is_hex(pin.get(k), 64) for k in (
                "first_sha256", "last_sha256", "history_sha256",
                "v61_sources_sha256", "trust_sha256"))):
        return ["invalid_custody_history_pin"], 0
    errors, counted, previous = [], 0, None
    for i, snap in enumerate(view["snapshots"]):
        if (not isinstance(snap, dict) or set(snap) != {
                "snapshot", "previous_sha256", "sources"
            } or type(snap.get("snapshot")) is not int or
                snap["snapshot"] != pin["first_snapshot"] + i or
                not is_hex(snap.get("previous_sha256"), 64) or
                not isinstance(snap.get("sources"), dict) or
                set(snap["sources"]) != FIELDS):
            errors.append(f"invalid_or_missing_snapshot:{i}")
            previous = None
            continue
        data = snap["sources"]
        local_pin = data["independent_pin"]
        if (not isinstance(local_pin, dict) or
                type(local_pin.get("minimum_receipts")) is not int or
                type(local_pin.get("minimum_round")) is not int or
                local_pin["minimum_receipts"] < pin["minimum_receipts"] or
                local_pin["minimum_round"] < pin["minimum_round"] or
                canonical_hash(data["v61_sources"]) != pin["v61_sources_sha256"] or
                canonical_hash(data["trust"]) != pin["trust_sha256"]):
            errors.append(f"external_trust_or_history_substitution:{i}")
            previous = None
            continue
        try:
            result = assess_v62(*(data[k] for k in (
                "v61_sources", "copies", "trust", "independent_pin")))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError,
                OverflowError, RecursionError, MemoryError) as exc:
            errors.append(f"malformed_v62:{i}:{type(exc).__name__}")
            previous = None
            continue
        if not result["custody_evidence_valid"]:
            errors.extend(f"v62:{i}:{e}" for e in result["errors"])
            previous = None
            continue
        counted += 1
        if i == 0:
            if snap["previous_sha256"] != ZERO:
                errors.append("invalid_genesis_link")
            if canonical_hash(snap) != pin["first_sha256"]:
                errors.append("first_snapshot_anchor_mismatch")
        else:
            if previous is None or snap["previous_sha256"] != canonical_hash(previous):
                errors.append(f"broken_snapshot_link:{i}")
            if previous is not None:
                old = previous["sources"]
                if (local_pin["minimum_receipts"] <
                        old["independent_pin"]["minimum_receipts"] or
                        local_pin["minimum_round"] <
                        old["independent_pin"]["minimum_round"]):
                    errors.append(f"custody_policy_rollback:{i}")
                if canonical_hash(data["copies"]) != canonical_hash(old["copies"]):
                    errors.append(f"conflicting_historical_receipt_register:{i}")
        if i == len(view["snapshots"]) - 1 and canonical_hash(snap) != pin["last_sha256"]:
            errors.append("last_snapshot_anchor_mismatch")
        previous = snap
    if canonical_hash(view) != pin["history_sha256"]:
        errors.append("independent_custody_history_anchor_mismatch")
    return errors, counted


def assess(left, left_pin, right, right_pin, head):
    try:
        for obj in (left, left_pin, right, right_pin, head):
            validate_shape(obj)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(head, dict) or set(head) != {
                "schema", "expected_history_sha256", "minimum_last_snapshot",
                "minimum_receipts", "minimum_round"
            } or head.get("schema") != HEAD_SCHEMA or
            not is_hex(head.get("expected_history_sha256"), 64) or
            any(type(head.get(k)) is not int or head[k] < bound for k, bound in (
                ("minimum_last_snapshot", 2),
                ("minimum_receipts", 2), ("minimum_round", 2)))):
        return verdict(["invalid_independent_head"])
    errors, counted = [], 0
    for label, view, pin in (("left", left, left_pin), ("right", right, right_pin)):
        issues, verified = assess_view(view, pin)
        errors.extend(f"{label}:{e}" for e in issues)
        counted += verified
    if errors:
        return verdict(errors, counted)
    if (left_pin["first_snapshot"] != right_pin["first_snapshot"] or
            left_pin["last_snapshot"] != right_pin["last_snapshot"]):
        errors.append("observer_snapshot_window_conflict")
    if left_pin["last_snapshot"] < head["minimum_last_snapshot"]:
        errors.append("independent_snapshot_rollback")
    if any(pin["minimum_receipts"] < head["minimum_receipts"] or
           pin["minimum_round"] < head["minimum_round"] for pin in (left_pin, right_pin)):
        errors.append("external_retention_or_quorum_downgrade")
    a, b = canonical_hash(left), canonical_hash(right)
    if a != b:
        errors.append("contradictory_archival_receipt_histories")
    if a != head["expected_history_sha256"]:
        errors.append("left_external_head_mismatch")
    if b != head["expected_history_sha256"]:
        errors.append("right_external_head_mismatch")
    return verdict(errors, counted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("left", "left-pin", "right", "right-pin", "independent-head"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_evidence_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = assess(*(read(getattr(args, name.replace("-", "_"))) for name in (
            "left", "left-pin", "right", "right-pin", "independent-head")))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["custody_succession_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
