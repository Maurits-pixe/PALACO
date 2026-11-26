#!/usr/bin/env python3
"""GO-20 v26: bounded, fail-closed governance evidence hardening gate.

Always emits HOLD/DENY. It does not write files, mutate Github,
approve, merge or invoke production interfaces. Source input is untrusted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, unique_pairs
from pr_governance_history import verify_history

SCHEMA = "palaco.go20-governance-hardening-verdict.v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 250000
MAX_STRING = 1000000


def fail(errors: list[str], verified: bool = False) -> dict:
    return {
        "schema": SCHEMA,
        "evidence_valid": verified and not errors,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
        "note": "Offline assessment only; no external trust anchors are established.",
    }


def validate_shape(obj: object) -> None:
    """Reject resource exhaustion, non-JSON values, excess nesting and wide objects."""
    pending = [(obj, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise ValueError("node_limit")
        if depth > MAX_DEPTH:
            raise ValueError("depth_limit")
        if isinstance(value, dict):
            if len(value) > MAX_NODES:
                raise ValueError("mapping_limit")
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > MAX_STRING:
                    raise ValueError("invalid_key")
                pending.append((child, depth + 1))
        elif isinstance(value, list):
            if len(value) > MAX_NODES:
                raise ValueError("list_limit")
            pending.extend((child, depth + 1) for child in value)
        elif isinstance(value, str):
            if len(value) > MAX_STRING:
                raise ValueError("string_limit")
        elif value is None or isinstance(value, bool) or type(value) is int:
            continue
        else:
            raise ValueError("non_canonical_value")


def harden(history: object, independent_pin: object, controller_trust: object) -> dict:
    try:
        for source in (history, independent_pin, controller_trust):
            validate_shape(source)
        # Proof-level evidence is never self-anchored: all three inputs stay separate.
        checked = verify_history(history, independent_pin, controller_trust)
        if not isinstance(checked, dict) or checked.get("history_valid") is not True:
            issues = checked.get("errors", []) if isinstance(checked, dict) else []
            return fail(["governance_history_invalid"] + [
                str(issue)[:180] for issue in issues if isinstance(issue, str)
            ])
        if (checked.get("decision") != "HOLD" or
                checked.get("authorization") != "DENY" or
                checked.get("release_authorized") is not False or
                checked.get("merge_authorized") is not False or
                checked.get("deployment_authorized") is not False or
                checked.get("production_commit_performed") is not False):
            return fail(["governance_verdict_authority_violation"])
        return fail([], verified=True)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError,
            RecursionError, OverflowError, MemoryError) as exc:
        return fail(["malformed_governance_evidence:" + type(exc).__name__])


def read(path: Path) -> object:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("missing_or_oversize_input")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non_finite_number")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--independent-pin", type=Path, required=True)
    parser.add_argument("--controller-trust", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = harden(read(args.history), read(args.independent_pin),
                        read(args.controller_trust))
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError,
            RecursionError, MemoryError) as exc:
        output = fail(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
