#!/usr/bin/env python3
"""GO-20 v40: fail-closed compare of two independently exported restore ledgers.

This checks snapshot consistency and an externally pinned source digest.
It is NOT physical/logical replication, leader election, or failover.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "palaco.go20-restore-handoff-verdict.v1"
FIELDS = ("request_id", "manifest_sha256", "pin_sha256", "segments_sha256")


def result(issues, records=0):
    return {
        "schema": SCHEMA,
        "handoff_consistent": not issues,
        "rows_compared": records,
        "errors": sorted(set(issues)),
        "decision": "HOLD",
        "authorization": "DENY",
        "failover_authorized": False,
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def canonical(rows):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("invalid_rows")
    seen_ids, seen_material = set(), set()
    out = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError("invalid_row")
        req = row["request_id"]
        values = tuple(row[f] for f in FIELDS[1:])
        if (not isinstance(req, str) or not 1 <= len(req) <= 128 or
                any(not isinstance(v, str) or len(v) != 64 or
                    any(c not in "0123456789abcdef" for c in v) for v in values)):
            raise ValueError("invalid_field")
        if req in seen_ids or values in seen_material:
            raise ValueError("duplicate_claim")
        seen_ids.add(req)
        seen_material.add(values)
        out.append((req, *values))
    return sorted(out)


def digest(records):
    return hashlib.sha256(json.dumps(records, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def verify(primary, candidate, anchor):
    try:
        if (not isinstance(anchor, dict) or set(anchor) != {
                "schema", "primary_sha256", "minimum_rows"
        } or anchor["schema"] != "palaco.go20-restore-handoff-pin.v1" or
                not isinstance(anchor["primary_sha256"], str) or
                len(anchor["primary_sha256"]) != 64 or
                any(c not in "0123456789abcdef" for c in anchor["primary_sha256"]) or
                type(anchor["minimum_rows"]) is not int or anchor["minimum_rows"] < 1):
            return result(["invalid_independent_source_anchor"])
        left, right = canonical(primary), canonical(candidate)
        issues = []
        if digest(left) != anchor["primary_sha256"]:
            issues.append("source_anchor_mismatch")
        if len(left) < anchor["minimum_rows"]:
            issues.append("source_retention_floor")
        if left != right:
            issues.append("snapshot_divergence_or_missing_claims")
        return result(issues, len(left) if left == right else 0)
    except (ValueError, TypeError, KeyError, OverflowError, MemoryError, RecursionError):
        return result(["malformed_ledger_snapshot"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("primary", "candidate", "independent-pin"):
        parser.add_argument("--" + key, type=Path, required=True)
    opts = parser.parse_args()
    try:
        def load(path):
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError("missing_or_oversize")
            def reject_dupes(pairs):
                obj = {}
                for key, val in pairs:
                    if key in obj:
                        raise ValueError("duplicate_json_key")
                    obj[key] = val
                return obj
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=reject_dupes)
        output = verify(load(opts.primary), load(opts.candidate),
                        load(opts.independent_pin))
    except (OSError, ValueError, UnicodeError, TypeError, MemoryError) as exc:
        output = result(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if output["handoff_consistent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
