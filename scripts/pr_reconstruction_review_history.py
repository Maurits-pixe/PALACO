#!/usr/bin/env python3
"""GO-20 v59: externally anchored reconstruction review succession and forks.

Reverify each full v58 evidence package in two independent observer histories.
Consecutive rounds must hash-link, retain the original v57 evidence and the
reviewer trust registry, and keep the same canonical reconstruction content.
Two self-consistent but divergent views are denied. This is offline-only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_isolated_evidence_reconstruction import assess as assess_v58

SCHEMA = "palaco.go20-reconstruction-review-history.v1"
PIN_SCHEMA = "palaco.go20-reconstruction-review-history-pin.v1"
HEAD_SCHEMA = "palaco.go20-reconstruction-review-head-pin.v1"
ZERO = "0" * 64
MAX_ROUNDS = 4
SOURCE_FIELDS = {"v57", "reconstruction", "reviewers", "pin", "observed_at"}


def verdict(errors, rounds=0):
    return {
        "schema": "palaco.go20-reconstruction-review-history-verdict.v1",
        "review_history_valid": not errors,
        "rounds_verified": rounds,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "report_promoted": False,
        "trust_registry_promoted": False,
        "history_restored": False,
        "physical_media_verified": False,
        "production_restoration_performed": False,
        "failover_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def assess_view(view, pin):
    if (not isinstance(view, dict) or set(view) != {"schema", "rounds"} or
            view.get("schema") != SCHEMA or
            not isinstance(view.get("rounds"), list) or
            not 2 <= len(view["rounds"]) <= MAX_ROUNDS):
        return ["invalid_review_history"], 0
    if (not isinstance(pin, dict) or set(pin) != {
                "schema", "first_round", "last_round", "first_round_sha256",
                "last_round_sha256", "view_sha256", "v57_sha256",
                "reviewer_trust_sha256", "minimum_reviews"
            } or pin.get("schema") != PIN_SCHEMA or
            any(type(pin.get(k)) is not int or pin[k] < bound for k, bound in (
                ("first_round", 1), ("last_round", 2), ("minimum_reviews", 2))) or
            pin["last_round"] != pin["first_round"] + len(view["rounds"]) - 1 or
            any(not is_hex(pin.get(k), 64) for k in (
                "first_round_sha256", "last_round_sha256", "view_sha256",
                "v57_sha256", "reviewer_trust_sha256"))):
        return ["invalid_review_history_pin"], 0
    errors, count = [], 0
    previous = None
    for i, round_item in enumerate(view["rounds"]):
        if (not isinstance(round_item, dict) or set(round_item) != {
                "round", "previous_round_sha256", "sources"
            } or type(round_item.get("round")) is not int or
                round_item["round"] != pin["first_round"] + i or
                not is_hex(round_item.get("previous_round_sha256"), 64) or
                not isinstance(round_item.get("sources"), dict) or
                set(round_item["sources"]) != SOURCE_FIELDS):
            errors.append(f"invalid_or_missing_round:{i}")
            previous = None
            continue
        source = round_item["sources"]
        if (canonical_hash(source["v57"]) != pin["v57_sha256"] or
                canonical_hash(source["reviewers"]) != pin["reviewer_trust_sha256"] or
                source["pin"].get("minimum_reviews", 0) < pin["minimum_reviews"]):
            errors.append(f"external_trust_or_evidence_substitution:{i}")
            previous = None
            continue
        if type(source["observed_at"]) is not int:
            errors.append(f"invalid_observation_time:{i}")
            previous = None
            continue
        try:
            result = assess_v58(
                source["v57"], source["reconstruction"],
                source["reviewers"], source["pin"], source["observed_at"])
        except (ValueError, TypeError, KeyError, IndexError, AttributeError,
                OverflowError, RecursionError, MemoryError) as exc:
            errors.append(f"malformed_v58:{i}:{type(exc).__name__}")
            previous = None
            continue
        if not result["isolated_evidence_valid"]:
            errors.extend(f"v58:{i}:{e}" for e in result["errors"])
            previous = None
            continue
        count += 1
        if i == 0:
            if round_item["previous_round_sha256"] != ZERO:
                errors.append("invalid_genesis_link")
            if canonical_hash(round_item) != pin["first_round_sha256"]:
                errors.append("first_round_anchor_mismatch")
        else:
            if previous is None or round_item["previous_round_sha256"] != canonical_hash(previous):
                errors.append(f"broken_round_link:{i}")
            if previous is not None:
                previous_source = previous["sources"]
                if (canonical_hash(source["reconstruction"]) !=
                        canonical_hash(previous_source["reconstruction"])):
                    errors.append(f"conflicting_reconstruction_results:{i}")
                if (source["pin"]["minimum_copies"] <
                        previous_source["pin"]["minimum_copies"] or
                        source["pin"]["minimum_reviews"] <
                        previous_source["pin"]["minimum_reviews"]):
                    errors.append(f"weakened_review_policy:{i}")
        if i == len(view["rounds"]) - 1 and canonical_hash(round_item) != pin["last_round_sha256"]:
            errors.append("last_round_anchor_mismatch")
        previous = round_item
    if canonical_hash(view) != pin["view_sha256"]:
        errors.append("external_review_history_anchor_mismatch")
    return errors, count


def assess(left, left_pin, right, right_pin, head):
    try:
        for data in (left, left_pin, right, right_pin, head):
            validate_shape(data)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(head, dict) or set(head) != {
                "schema", "expected_view_sha256", "minimum_last_round"
            } or head.get("schema") != HEAD_SCHEMA or
            not is_hex(head.get("expected_view_sha256"), 64) or
            type(head.get("minimum_last_round")) is not int or
            head["minimum_last_round"] < 2):
        return verdict(["invalid_independent_head"])
    errors, checked = [], 0
    for label, view, pin in (("left", left, left_pin), ("right", right, right_pin)):
        issues, count = assess_view(view, pin)
        errors.extend(f"{label}:{issue}" for issue in issues)
        checked += count
    if errors:
        return verdict(errors, checked)
    if (left_pin["first_round"] != right_pin["first_round"] or
            left_pin["last_round"] != right_pin["last_round"]):
        errors.append("observer_round_window_mismatch")
    if left_pin["last_round"] < head["minimum_last_round"]:
        errors.append("review_history_rollback")
    a, b = canonical_hash(left), canonical_hash(right)
    if a != b:
        errors.append("contradictory_reconstruction_reports")
    if a != head["expected_view_sha256"]:
        errors.append("left_external_head_mismatch")
    if b != head["expected_view_sha256"]:
        errors.append("right_external_head_mismatch")
    return verdict(errors, checked)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("left", "left-pin", "right", "right-pin", "independent-head"):
        p.add_argument("--" + name, required=True, type=Path)
    args = p.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_evidence_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = assess(*(read(getattr(args, name.replace("-", "_"))) for name in (
            "left", "left-pin", "right", "right-pin", "independent-head")))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["review_history_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
