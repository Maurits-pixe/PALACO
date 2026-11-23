#!/usr/bin/env python3
"""GO-20 v35: ephemeral SQLite restore transaction and fault-injection proof.

Runs the v34 segmented recovery verifier before inserting any data. A fresh
SQLite :memory: database is used, never a path/DSN; faults inject exceptions
inside a single transaction. A successful sandbox commit is NOT a production
restore or authorization. Requires independently sourced v34 pins.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from pr_audit_integrity import canonical_hash, unique_pairs
from pr_governance_hardening import validate_shape
from pr_recovery_simulation import simulate

SCHEMA = "palaco.go20-recovery-transaction-proof.v1"
FAULT_POINTS = ("none", "after_begin", "after_first_segment", "before_commit")
MAX_SEGMENTS = 13


def verdict(errors: list[str], expected: int = 0, committed: int = 0,
            rolled_back: bool = False, sandbox_committed: bool = False) -> dict:
    return {
        "schema": SCHEMA,
        "transaction_valid": not errors,
        "expected_segments": expected,
        "sandbox_rows_after_transaction": committed,
        "sandbox_commit_performed": sandbox_committed,
        "rollback_verified": rolled_back,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
        "restore_performed": False,
        "production_write_performed": False,
    }


def execute_sandbox(segments: object, manifest: object, independent_pin: object,
                    fault_point: str = "none") -> dict:
    if fault_point not in FAULT_POINTS:
        return verdict(["invalid_fault_point"])
    try:
        for item in (segments, manifest, independent_pin):
            validate_shape(item)
        preflight = simulate(segments, manifest, independent_pin)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_recovery_input:" + type(exc).__name__])
    if not preflight["simulation_valid"]:
        return verdict(["preflight:" + issue for issue in preflight["errors"]] or
                       ["preflight_failed"])
    if not isinstance(segments, dict) or not isinstance(segments.get("parts"), list):
        return verdict(["invalid_segment_package"])
    parts = segments["parts"]
    expected = len(parts)
    if not 7 <= expected <= MAX_SEGMENTS or len({p["name"] for p in parts}) != expected:
        return verdict(["invalid_segment_coverage"])
    con = sqlite3.connect(":memory:", isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("CREATE TABLE restore_fragments ("
                    "name TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL)")
        con.execute("CREATE TABLE restore_receipt ("
                    "id INTEGER PRIMARY KEY CHECK(id=1), manifest_digest TEXT NOT NULL, "
                    "segment_count INTEGER NOT NULL CHECK(segment_count >= 7))")
        errors = []
        try:
            con.execute("BEGIN IMMEDIATE")
            if fault_point == "after_begin":
                raise RuntimeError("injected_after_begin")
            for i, part in enumerate(parts):
                raw = json.dumps(part["content"], sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False)
                con.execute("INSERT INTO restore_fragments(name,digest,payload) VALUES(?,?,?)",
                            (part["name"], canonical_hash(part["content"]), raw))
                if i == 0 and fault_point == "after_first_segment":
                    raise RuntimeError("injected_after_first_segment")
            con.execute("INSERT INTO restore_receipt(id,manifest_digest,segment_count) "
                        "VALUES(1,?,?)", (canonical_hash(manifest), expected))
            count = con.execute("SELECT COUNT(*) FROM restore_fragments").fetchone()[0]
            receipt = con.execute("SELECT segment_count,manifest_digest "
                                  "FROM restore_receipt WHERE id=1").fetchone()
            if count != expected or receipt != (expected, canonical_hash(manifest)):
                raise ValueError("precommit_invariant_failure")
            if fault_point == "before_commit":
                raise RuntimeError("injected_before_commit")
            con.execute("COMMIT")
        except (RuntimeError, ValueError, sqlite3.Error) as exc:
            errors.append("rollback_trigger:" + str(exc))
            if con.in_transaction:
                con.execute("ROLLBACK")
            remaining = con.execute("SELECT COUNT(*) FROM restore_fragments").fetchone()[0]
            receipts = con.execute("SELECT COUNT(*) FROM restore_receipt").fetchone()[0]
            if remaining or receipts or con.in_transaction:
                errors.append("partial_restore_detected")
            return verdict(errors, expected, remaining,
                           rolled_back=not remaining and not receipts and not con.in_transaction)
        remaining = con.execute("SELECT COUNT(*) FROM restore_fragments").fetchone()[0]
        receipts = con.execute("SELECT COUNT(*) FROM restore_receipt").fetchone()[0]
        if remaining != expected or receipts != 1 or con.in_transaction:
            return verdict(["postcommit_invariant_failure"], expected, remaining,
                           sandbox_committed=True)
        return verdict([], expected, remaining, sandbox_committed=True)
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("segments", "manifest", "independent-pin"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--inject-fault", choices=FAULT_POINTS, default="none")
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_input")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = execute_sandbox(read(args.segments), read(args.manifest),
                                 read(args.independent_pin), args.inject_fault)
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError, MemoryError, sqlite3.Error) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["transaction_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
