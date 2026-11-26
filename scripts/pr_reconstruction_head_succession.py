#!/usr/bin/env python3
"""GO-20 v61: anchored v60 witness succession and revocation permanence.

Fully re-verify each v60 package in every historical round, with an immutable
reconstruction evidence head and strictly monotonic externally anchored
reviewer-key revocations. Compare two independently supplied observation
views and reject conflicting recovery assertions. Read-only offline evidence.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_reconstruction_head_witnesses import assess as assess_v60

SCHEMA = "palaco.go20-reconstruction-head-succession.v1"
PIN_SCHEMA = "palaco.go20-reconstruction-head-succession-pin.v1"
HEAD_SCHEMA = "palaco.go20-reconstruction-head-succession-independent-head.v1"
ZERO = "0" * 64
FIELDS = {"v59_sources", "head_witnesses", "witness_trust", "reviewer_revocations", "independent_pin"}


def verdict(errors, verified=0):
    return {
        "schema": "palaco.go20-reconstruction-head-succession-verdict.v1",
        "succession_evidence_valid": not errors,
        "rounds_verified": verified,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "revocations_enforced_in_production": False,
        "recovery_performed": False,
        "recovery_authorized": False,
        "trust_registry_promoted": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def validate_history(view, pin):
    if (not isinstance(view, dict) or set(view) != {"schema", "rounds"} or
            view.get("schema") != SCHEMA or
            not isinstance(view.get("rounds"), list) or
            not 2 <= len(view["rounds"]) <= 4):
        return ["invalid_history"], 0
    if (not isinstance(pin, dict) or set(pin) != {
            "schema", "first_round", "last_round", "first_sha256",
            "last_sha256", "history_sha256", "v59_sha256",
            "witness_trust_sha256", "minimum_witnesses"
    } or pin.get("schema") != PIN_SCHEMA or
            any(type(pin.get(k)) is not int or pin[k] < minimum for k, minimum in (
                ("first_round", 1), ("last_round", 2), ("minimum_witnesses", 2))) or
            pin["last_round"] != pin["first_round"] + len(view["rounds"]) - 1 or
            any(not is_hex(pin.get(k), 64) for k in (
                "first_sha256", "last_sha256", "history_sha256",
                "v59_sha256", "witness_trust_sha256"))):
        return ["invalid_history_pin"], 0
    errors, count, previous, retained = [], 0, None, {}
    for i, item in enumerate(view["rounds"]):
        if (not isinstance(item, dict) or set(item) != {
                "round", "previous_sha256", "evidence"
            } or type(item.get("round")) is not int or
                item["round"] != pin["first_round"] + i or
                not is_hex(item.get("previous_sha256"), 64) or
                not isinstance(item.get("evidence"), dict) or
                set(item["evidence"]) != FIELDS):
            errors.append(f"invalid_or_missing_round:{i}")
            previous = None
            continue
        source = item["evidence"]
        v60pin = source["independent_pin"]
        if (not isinstance(v60pin, dict) or
                type(v60pin.get("minimum_witnesses")) is not int or
                v60pin["minimum_witnesses"] < pin["minimum_witnesses"] or
                canonical_hash(source["v59_sources"]) != pin["v59_sha256"] or
                canonical_hash(source["witness_trust"]) != pin["witness_trust_sha256"]):
            errors.append(f"witness_trust_or_v59_substitution:{i}")
            previous = None
            continue
        try:
            result = assess_v60(*(source[k] for k in (
                "v59_sources", "head_witnesses", "witness_trust",
                "reviewer_revocations", "independent_pin")))
        except (TypeError, ValueError, KeyError, IndexError, AttributeError,
                OverflowError, RecursionError, MemoryError) as exc:
            errors.append(f"malformed_v60:{i}:{type(exc).__name__}")
            previous = None
            continue
        if not result["head_evidence_valid"]:
            errors.extend(f"v60:{i}:{e}" for e in result["errors"])
            previous = None
            continue
        count += 1
        if i == 0:
            if item["previous_sha256"] != ZERO:
                errors.append("invalid_genesis")
            if canonical_hash(item) != pin["first_sha256"]:
                errors.append("first_round_anchor_mismatch")
        else:
            if previous is None or item["previous_sha256"] != canonical_hash(previous):
                errors.append(f"broken_succession_link:{i}")
            if previous is not None:
                old = previous["evidence"]
                if v60pin["minimum_last_round"] < old["independent_pin"]["minimum_last_round"]:
                    errors.append(f"historical_round_floor_rollback:{i}")
                if v60pin["minimum_witnesses"] < old["independent_pin"]["minimum_witnesses"]:
                    errors.append(f"witness_quorum_downgrade:{i}")
                if (canonical_hash(source["head_witnesses"]["decisions"]) !=
                        canonical_hash(old["head_witnesses"]["decisions"])):
                    errors.append(f"conflicting_recovery_assertion:{i}")
        current = {}
        for entry in source["reviewer_revocations"]["entries"]:
            key = (entry["reviewer_id"], entry["public_key_hex"])
            current[key] = entry["effective_round"]
        for key, when in retained.items():
            if key not in current or current[key] != when:
                errors.append(f"revocation_removed_or_redated:{i}")
        retained = current
        if i == len(view["rounds"]) - 1 and canonical_hash(item) != pin["last_sha256"]:
            errors.append("last_round_anchor_mismatch")
        previous = item
    if canonical_hash(view) != pin["history_sha256"]:
        errors.append("independent_history_anchor_mismatch")
    return errors, count


def assess(left, left_pin, right, right_pin, external_head):
    try:
        for value in (left, left_pin, right, right_pin, external_head):
            validate_shape(value)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(external_head, dict) or set(external_head) != {
                "schema", "history_sha256", "minimum_last_round",
                "minimum_witnesses"
            } or external_head.get("schema") != HEAD_SCHEMA or
            not is_hex(external_head.get("history_sha256"), 64) or
            type(external_head.get("minimum_last_round")) is not int or
            external_head["minimum_last_round"] < 2 or
            type(external_head.get("minimum_witnesses")) is not int or
            external_head["minimum_witnesses"] < 2):
        return verdict(["invalid_independent_head"])
    errors, count = [], 0
    for label, view, pin in (("left", left, left_pin), ("right", right, right_pin)):
        issues, checked = validate_history(view, pin)
        errors.extend(f"{label}:{err}" for err in issues)
        count += checked
    if errors:
        return verdict(errors, count)
    if (left_pin["first_round"] != right_pin["first_round"] or
            left_pin["last_round"] != right_pin["last_round"]):
        errors.append("observer_round_window_conflict")
    if left_pin["last_round"] < external_head["minimum_last_round"]:
        errors.append("independent_head_rollback")
    if (left_pin["minimum_witnesses"] < external_head["minimum_witnesses"] or
            right_pin["minimum_witnesses"] < external_head["minimum_witnesses"]):
        errors.append("external_witness_floor_downgrade")
    a, b = canonical_hash(left), canonical_hash(right)
    if a != b:
        errors.append("conflicting_reconstruction_head_histories")
    if a != external_head["history_sha256"]:
        errors.append("left_external_head_mismatch")
    if b != external_head["history_sha256"]:
        errors.append("right_external_head_mismatch")
    return verdict(errors, count)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("left", "left-pin", "right", "right-pin", "independent-head"):
        p.add_argument("--" + name, required=True, type=Path)
    args = p.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_input")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = assess(*(read(getattr(args, name.replace("-", "_"))) for name in (
            "left", "left-pin", "right", "right-pin", "independent-head")))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["succession_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
