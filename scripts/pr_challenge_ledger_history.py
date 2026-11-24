#!/usr/bin/env python3
"""GO-20 v51: signed, consecutive ledger checkpoints and two-view fork detection.

Every historical snapshot must independently satisfy GO-20 v50. Histories
must have immutable prior rows, monotonic consumptions and hash-linked,
consecutive checkpoints; both views must match an external fixed head.
Offline evidence verifier only: does not publish, restore or grant authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_challenge_ledger_checkpoint import assess as assess_v50

SCHEMA = "palaco.go20-challenge-ledger-history.v1"
PIN_SCHEMA = "palaco.go20-challenge-ledger-history-pin.v1"
ENTRY_FIELDS = {"rows", "checkpoint", "independent_pin", "signature"}
MAX_ENTRIES = 6


def verdict(errors, histories=0, checkpoints=0):
    return {
        "schema": "palaco.go20-challenge-ledger-history-verdict.v1",
        "history_evidence_valid": not errors,
        "histories_verified": histories,
        "checkpoints_verified": checkpoints,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "restoration_performed": False,
        "ledger_promoted": False,
        "challenge_reopened": False,
        "failover_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess_view(history, pin):
    if (not isinstance(history, dict) or set(history) != {"schema", "entries"} or
            history.get("schema") != SCHEMA or
            not isinstance(history.get("entries"), list) or
            not 2 <= len(history["entries"]) <= MAX_ENTRIES):
        return ["invalid_history"], 0
    if (not isinstance(pin, dict) or set(pin) != {
            "schema", "first_sequence", "last_sequence", "first_checkpoint_sha256",
            "last_checkpoint_sha256", "history_sha256", "minimum_rows",
            "minimum_consumed"
    } or pin.get("schema") != PIN_SCHEMA or
            any(type(pin.get(k)) is not int or pin[k] < minimum for k, minimum in (
                ("first_sequence", 1), ("last_sequence", 2),
                ("minimum_rows", 1), ("minimum_consumed", 0))) or
            pin["last_sequence"] != pin["first_sequence"] + len(history["entries"]) - 1 or
            any(not is_hex(pin.get(k), 64) for k in (
                "first_checkpoint_sha256", "last_checkpoint_sha256", "history_sha256"))):
        return ["invalid_independent_history_pin"], 0
    errors, verified, previous = [], 0, None
    for index, entry in enumerate(history["entries"]):
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            errors.append(f"invalid_entry:{index}")
            continue
        cp = entry["checkpoint"]
        rows = entry["rows"]
        if (not isinstance(cp, dict) or
                type(cp.get("sequence")) is not int or
                cp["sequence"] != pin["first_sequence"] + index):
            errors.append(f"checkpoint_sequence_gap:{index}")
            continue
        try:
            result = assess_v50(
                rows, cp, entry["independent_pin"], entry["signature"])
        except (TypeError, ValueError, KeyError, IndexError,
                AttributeError, OverflowError, RecursionError, MemoryError) as exc:
            errors.append(f"malformed_v50:{index}:{type(exc).__name__}")
            continue
        if not result["ledger_checkpoint_valid"]:
            errors.extend(f"v50:{index}:{e}" for e in result["errors"])
            continue
        verified += 1
        if index == 0 and canonical_hash(cp) != pin["first_checkpoint_sha256"]:
            errors.append("first_checkpoint_mismatch")
        if index == len(history["entries"]) - 1 and canonical_hash(cp) != pin["last_checkpoint_sha256"]:
            errors.append("last_checkpoint_mismatch")
        if previous is not None:
            prevcp = previous["checkpoint"]
            if cp["previous_checkpoint_sha256"] != canonical_hash(prevcp):
                errors.append(f"checkpoint_link_mismatch:{index}")
            if cp["row_count"] < prevcp["row_count"] or cp["minimum_consumed"] < prevcp["minimum_consumed"]:
                errors.append(f"retention_rollback:{index}")
            if (entry["independent_pin"]["public_key_hex"] !=
                    previous["independent_pin"]["public_key_hex"] or
                    entry["independent_pin"]["key_id"] !=
                    previous["independent_pin"]["key_id"]):
                errors.append(f"unexpected_signer_rotation:{index}")
            before = {row["nonce_sha256"]: row for row in previous["rows"]}
            after = {row["nonce_sha256"]: row for row in rows}
            if not before.keys() <= after.keys():
                errors.append(f"deleted_challenge:{index}")
            for nonce, old in before.items():
                if nonce not in after:
                    continue
                new = after[nonce]
                static = ("nonce_sha256", "challenge_sha256", "issued_at", "expires_at")
                if any(old[k] != new[k] for k in static):
                    errors.append(f"challenge_rewritten:{index}")
                if old["state"] == "CONSUMED" and new != old:
                    errors.append(f"consumed_challenge_reopened_or_changed:{index}")
                if (old["state"] == "ISSUED" and
                        (new["state"] not in ("ISSUED", "CONSUMED") or
                         (new["state"] == "ISSUED" and new != old))):
                    errors.append(f"challenge_invalid_transition:{index}")
        previous = entry
    if canonical_hash(history) != pin["history_sha256"]:
        errors.append("independent_history_anchor_mismatch")
    return errors, verified


def assess(left, left_pin, right, right_pin, independent_head):
    try:
        for source in (left, left_pin, right, right_pin, independent_head):
            validate_shape(source)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(independent_head, dict) or set(independent_head) != {
            "schema", "expected_history_sha256", "minimum_last_sequence"
    } or independent_head.get("schema") != "palaco.go20-challenge-ledger-head-pin.v1" or
            not is_hex(independent_head.get("expected_history_sha256"), 64) or
            type(independent_head.get("minimum_last_sequence")) is not int or
            independent_head["minimum_last_sequence"] < 2):
        return verdict(["invalid_independent_head_pin"])
    errors, checked = [], 0
    for label, history, pin in (("left", left, left_pin), ("right", right, right_pin)):
        issues, verified = assess_view(history, pin)
        errors.extend(f"{label}:{e}" for e in issues)
        checked += verified
    if errors:
        return verdict(errors, 0, checked)
    if (left_pin["first_sequence"] != right_pin["first_sequence"] or
            left_pin["last_sequence"] != right_pin["last_sequence"]):
        errors.append("fork_sequence_window_mismatch")
    if left_pin["last_sequence"] < independent_head["minimum_last_sequence"]:
        errors.append("checkpoint_head_rollback")
    a, b = canonical_hash(left), canonical_hash(right)
    if a != b:
        errors.append("ledger_history_fork_detected")
    if a != independent_head["expected_history_sha256"]:
        errors.append("left_external_head_mismatch")
    if b != independent_head["expected_history_sha256"]:
        errors.append("right_external_head_mismatch")
    return verdict(errors, 2, checked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("left-history", "left-pin", "right-history", "right-pin", "independent-head")
    for name in names:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_evidence_file")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = assess(*(read(getattr(args, name.replace("-", "_"))) for name in names))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["history_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
