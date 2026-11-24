#!/usr/bin/env python3
"""GO-20 v50: offline SQLite challenge-ledger rollback and recovery proof.

Verifies a consistent READ-ONLY SQLite snapshot against an independently
pinned Ed25519-signed checkpoint. No self-attested rollback protection:
a trusted verifier MUST retain the pin and signer key outside SQLite.
Never writes to, migrates or restores any source database.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature

SCHEMA = "palaco.go20-challenge-ledger-checkpoint.v1"
PIN_SCHEMA = "palaco.go20-challenge-ledger-independent-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-challenge-ledger-checkpoint-statement.v1"
FIELDS = ("nonce_sha256", "challenge_sha256", "issued_at", "expires_at",
          "consumed_at", "state")
MAX_ROWS = 10000


def verdict(errors, checked=0):
    return {
        "schema": "palaco.go20-challenge-ledger-checkpoint-verdict.v1",
        "ledger_checkpoint_valid": not errors,
        "rows_verified": checked,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "database_restored": False,
        "rollback_recovery_authorized": False,
        "challenge_reopened": False,
        "failover_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def snapshot(database):
    path = Path(database)
    if (not path.is_absolute() or not path.is_file() or
            path.is_symlink() or path.stat().st_size > 32 * 1024 * 1024):
        raise ValueError("invalid_test_database")
    # URI mode=ro prevents accidental creation and writes; query_only is a
    # second fence. SQLite read transaction provides a consistent table view.
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='challenge_ledger'").fetchone()
        if table is None:
            raise ValueError("missing_ledger")
        columns = tuple(row[1] for row in db.execute("PRAGMA table_info(challenge_ledger)"))
        if columns != FIELDS:
            raise ValueError("invalid_ledger_schema")
        rows = db.execute(
            "SELECT nonce_sha256,challenge_sha256,issued_at,expires_at,"
            "consumed_at,state FROM challenge_ledger ORDER BY nonce_sha256 LIMIT ?",
            (MAX_ROWS + 1,)).fetchall()
        if len(rows) > MAX_ROWS:
            raise ValueError("ledger_limit_exceeded")
        seen_challenges = set()
        out = []
        for record in rows:
            nonce, challenge, issued, expires, consumed, state = record
            if (not is_hex(nonce, 64) or not is_hex(challenge, 64) or
                    challenge in seen_challenges or
                    type(issued) is not int or type(expires) is not int or
                    issued < 0 or expires <= issued or
                    state not in ("ISSUED", "CONSUMED") or
                    (state == "ISSUED" and consumed is not None) or
                    (state == "CONSUMED" and
                     (type(consumed) is not int or not issued <= consumed < expires))):
                raise ValueError("invalid_ledger_row")
            seen_challenges.add(challenge)
            out.append(dict(zip(FIELDS, record)))
        db.execute("COMMIT")
        return out
    finally:
        db.close()


def assess(rows, checkpoint, external_pin, signature):
    if (not isinstance(rows, list) or len(rows) > MAX_ROWS or
            not isinstance(checkpoint, dict) or set(checkpoint) != {
                "schema", "repository", "sequence", "rows_sha256", "row_count",
                "minimum_consumed", "previous_checkpoint_sha256"
            } or checkpoint.get("schema") != SCHEMA or
            checkpoint.get("repository") != "Maurits-pixe/PALACO" or
            type(checkpoint.get("sequence")) is not int or checkpoint["sequence"] < 1 or
            type(checkpoint.get("row_count")) is not int or checkpoint["row_count"] < 1 or
            type(checkpoint.get("minimum_consumed")) is not int or
            checkpoint["minimum_consumed"] < 0 or
            not is_hex(checkpoint.get("rows_sha256"), 64) or
            not is_hex(checkpoint.get("previous_checkpoint_sha256"), 64)):
        return verdict(["invalid_checkpoint"])
    if (not isinstance(external_pin, dict) or set(external_pin) != {
                "schema", "key_id", "public_key_hex", "checkpoint_sha256",
                "minimum_sequence", "minimum_rows", "minimum_consumed"
            } or external_pin.get("schema") != PIN_SCHEMA or
            not isinstance(external_pin.get("key_id"), str) or
            not external_pin["key_id"] or
            not is_hex(external_pin.get("public_key_hex"), 64) or
            not is_hex(external_pin.get("checkpoint_sha256"), 64) or
            any(type(external_pin.get(k)) is not int or
                external_pin[k] < lower for k, lower in (
                    ("minimum_sequence", 1), ("minimum_rows", 1),
                    ("minimum_consumed", 0)))):
        return verdict(["invalid_independent_checkpoint_pin"])
    if (not isinstance(signature, dict) or set(signature) != {
                "key_id", "signature_ed25519_hex"
            } or signature.get("key_id") != external_pin["key_id"] or
            not is_hex(signature.get("signature_ed25519_hex"), 128)):
        return verdict(["invalid_checkpoint_signature"])
    checkpoint_hash = canonical_hash(checkpoint)
    if checkpoint_hash != external_pin["checkpoint_sha256"]:
        return verdict(["independent_checkpoint_anchor_mismatch"])
    statement = {
        "schema": STATEMENT_SCHEMA,
        "repository": "Maurits-pixe/PALACO",
        "checkpoint_sha256": checkpoint_hash,
        "key_id": external_pin["key_id"],
        "decision": "HOLD", "authorization": "DENY",
    }
    issue = verify_signature(
        external_pin["public_key_hex"], signature["signature_ed25519_hex"],
        statement)
    if issue:
        return verdict(["checkpoint_signature_invalid:" + issue])
    if checkpoint["sequence"] < external_pin["minimum_sequence"]:
        return verdict(["checkpoint_sequence_rollback"])
    if (checkpoint["row_count"] < external_pin["minimum_rows"] or
            checkpoint["minimum_consumed"] < external_pin["minimum_consumed"]):
        return verdict(["retention_floor_rollback"])
    try:
        if not isinstance(rows, list) or any(
            not isinstance(r, dict) or set(r) != set(FIELDS)
            for r in rows
        ):
            return verdict(["invalid_rows"])
        if rows != sorted(rows, key=lambda r: r["nonce_sha256"]):
            return verdict(["unordered_rows"])
        if len(rows) != len({r["nonce_sha256"] for r in rows}):
            return verdict(["duplicate_nonces"])
        count = sum(r["state"] == "CONSUMED" for r in rows)
        if (len(rows) != checkpoint["row_count"] or
                len(rows) < external_pin["minimum_rows"] or
                count != checkpoint["minimum_consumed"] or
                count < external_pin["minimum_consumed"] or
                canonical_hash(rows) != checkpoint["rows_sha256"]):
            return verdict(["ledger_snapshot_divergence_or_rollback"])
        return verdict([], len(rows))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError, MemoryError):
        return verdict(["malformed_rows"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    for name in ("checkpoint", "independent-pin", "signature"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError("invalid_input_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        output = assess(snapshot(args.database), read(args.checkpoint),
                        read(args.independent_pin), read(args.signature))
    except (OSError, sqlite3.DatabaseError, ValueError, TypeError, KeyError,
            OverflowError, RecursionError, MemoryError, UnicodeError) as exc:
        output = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["ledger_checkpoint_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
