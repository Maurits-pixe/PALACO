#!/usr/bin/env python3
"""GO-20 v36: isolated concurrent restore claims with idempotent SQLite ledger.

Runs v34 cryptographic recovery preflight before any sandbox insert.
Multiple caller threads share one ephemeral SQLite :memory: connection,
serialized by an explicit mutex and database unique constraints. No
production DSN, filesystem writes, deployment or release authorization.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from pathlib import Path
from threading import Lock

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_recovery_simulation import simulate

SCHEMA = "palaco.go20-concurrent-restore-verdict.v1"
REQUEST_SCHEMA = "palaco.go20-concurrent-restore-requests.v1"
MAX_REQUESTS = 12


def verdict(errors: list[str], accepted: int = 0, replayed: int = 0,
            conflicts: int = 0, rows: int = 0, outcomes: list | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "claims_valid": not errors,
        "new_sandbox_commits": accepted,
        "idempotent_replays": replayed,
        "conflicts_rejected": conflicts,
        "sandbox_ledger_rows": rows,
        "request_outcomes": outcomes if outcomes is not None else [],
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
        "production_write_performed": False, "restore_performed": False,
    }


def evaluate(requests: object) -> dict:
    try:
        validate_shape(requests)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_request_structure:" + type(exc).__name__])
    if (not isinstance(requests, dict) or set(requests) != {"schema", "requests"} or
            requests.get("schema") != REQUEST_SCHEMA or
            not isinstance(requests["requests"], list) or
            not 1 <= len(requests["requests"]) <= MAX_REQUESTS):
        return verdict(["invalid_request_batch"])
    prepared = []
    for i, req in enumerate(requests["requests"]):
        if (not isinstance(req, dict) or set(req) != {
            "request_id", "segments", "manifest", "independent_pin"
        } or not isinstance(req.get("request_id"), str) or
                not 1 <= len(req["request_id"]) <= 128):
            return verdict([f"invalid_request:{i}"])
        try:
            checked = simulate(req["segments"], req["manifest"], req["independent_pin"])
        except (TypeError, ValueError, KeyError, IndexError, AttributeError,
                OverflowError, RecursionError, MemoryError) as exc:
            return verdict([f"invalid_preflight:{i}:{type(exc).__name__}"])
        if not checked["simulation_valid"]:
            return verdict([f"preflight:{i}:" + e for e in checked["errors"]])
        prepared.append((i, req["request_id"], canonical_hash(req["manifest"]),
                         canonical_hash(req["independent_pin"]),
                         canonical_hash(req["segments"])))

    # Runtime exists for this call only. SQL constraints and Python lock
    # are independent protections against concurrent double insertion.
    connection = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    mutex = Lock()
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE ledger ("
                           "request_id TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, "
                           "pin_sha256 TEXT NOT NULL, segments_sha256 TEXT NOT NULL)")
        connection.execute("CREATE UNIQUE INDEX unique_claim_material "
                           "ON ledger(manifest_sha256,pin_sha256,segments_sha256)")

        def submit(item):
            index, request_id, manifest_hash, pin_hash, segment_hash = item
            material = (manifest_hash, pin_hash, segment_hash)
            with mutex:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT manifest_sha256,pin_sha256,segments_sha256 "
                        "FROM ledger WHERE request_id=?", (request_id,)).fetchone()
                    if row is not None:
                        status = "idempotent_replay" if row == material else "request_id_conflict"
                    else:
                        owner = connection.execute(
                            "SELECT request_id FROM ledger WHERE "
                            "manifest_sha256=? AND pin_sha256=? AND segments_sha256=?",
                            material).fetchone()
                        if owner is not None:
                            status = "idempotent_replay"
                        else:
                            connection.execute("INSERT INTO ledger VALUES(?,?,?,?)",
                                               (request_id, *material))
                            status = "new_sandbox_commit"
                    connection.execute("COMMIT")
                    return {"index": index, "status": status}
                except sqlite3.Error:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    return {"index": index, "status": "sqlite_error"}

        with ThreadPoolExecutor(max_workers=min(8, len(prepared))) as pool:
            outcomes = sorted(pool.map(submit, prepared), key=lambda o: o["index"])
        statuses = [o["status"] for o in outcomes]
        commits = statuses.count("new_sandbox_commit")
        replays = statuses.count("idempotent_replay")
        conflicts = statuses.count("request_id_conflict")
        rows = connection.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
        errors = []
        if rows != commits:
            errors.append("nonatomic_or_duplicate_ledger_rows")
        if conflicts:
            errors.append("conflicting_idempotency_key")
        if any(s == "sqlite_error" for s in statuses):
            errors.append("sqlite_transaction_failure")
        if connection.in_transaction:
            errors.append("open_transaction")
        return verdict(errors, commits, replays, conflicts, rows, outcomes)
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    args = parser.parse_args()
    try:
        path = args.requests
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("missing_or_oversize_requests")
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        output = evaluate(data)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            RecursionError, MemoryError, sqlite3.Error) as exc:
        output = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["claims_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
