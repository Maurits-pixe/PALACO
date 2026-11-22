#!/usr/bin/env python3
"""GO-20 v10: disposable SQLite transaction integration harness.

This test-only harness creates its own TemporaryDirectory. No supplied DB
paths, no network, no PALACO database connection, no production authorization.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
from pathlib import Path

from pr_attestation_chain import digest
from pr_replay_transaction_contract import evaluate_transition

FAULT_POINTS = frozenset({"after_state_write", "after_receipts"})


class DisposableSQLiteReplay:
    """An isolated local SQLite transaction test fixture, never a service."""

    def __init__(self, initial_state: dict):
        self._temp = tempfile.TemporaryDirectory(prefix="palaco-go20-test-")
        self._database = Path(self._temp.name) / "replay.sqlite3"
        self._closed = False
        connection = self._connect()
        try:
            connection.execute("CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)")
            connection.execute("CREATE TABLE receipts (entry_sha256 TEXT PRIMARY KEY)")
            connection.execute(
                "INSERT INTO state (id, body) VALUES (1, ?)", (self._encode(initial_state),)
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._database), timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _encode(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def snapshot(self) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT body FROM state WHERE id=1").fetchone()
            return json.loads(row[0])

    def receipts(self) -> list[str]:
        with self._connect() as conn:
            return [row[0] for row in conn.execute(
                "SELECT entry_sha256 FROM receipts ORDER BY entry_sha256"
            )]

    def attempt(self, proposal: object, fault: str | None = None) -> dict:
        if self._closed:
            return self._verdict(["fixture_closed"])
        if fault is not None and fault not in FAULT_POINTS:
            return self._verdict(["invalid_fault_point"])
        connection = self._connect()
        try:
            # SQLite serializes writers at BEGIN IMMEDIATE. Validation and all
            # writes occur inside the SAME transaction.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT body FROM state WHERE id=1").fetchone()
            if row is None:
                connection.rollback()
                return self._verdict(["state_missing"])
            current = json.loads(row[0])
            transition = evaluate_transition(current, proposal)
            if not transition["preconditions_met"]:
                connection.rollback()
                return self._verdict(transition["errors"])
            candidate = transition["proposed_next_state"]
            hashes = proposal["entry_hashes"]
            for key in hashes:
                if connection.execute(
                    "SELECT 1 FROM receipts WHERE entry_sha256=?", (key,)
                ).fetchone():
                    connection.rollback()
                    return self._verdict(["duplicate_persisted_receipt"])
            connection.execute("UPDATE state SET body=? WHERE id=1", (self._encode(candidate),))
            if fault == "after_state_write":
                raise _InjectedRollback()
            for key in hashes:
                connection.execute("INSERT INTO receipts(entry_sha256) VALUES (?)", (key,))
            if fault == "after_receipts":
                raise _InjectedRollback()
            connection.commit()
            return self._verdict([], candidate)
        except _InjectedRollback:
            connection.rollback()
            return self._verdict(["injected_rollback"])
        except (sqlite3.Error, ValueError, TypeError, OverflowError):
            connection.rollback()
            return self._verdict(["sqlite_transaction_failed"])
        finally:
            connection.close()

    @staticmethod
    def _verdict(errors: list[str], candidate: dict | None = None) -> dict:
        return {
            "schema": "palaco.pr-sqlite-test-verdict.v1",
            "test_transaction_committed": candidate is not None,
            "test_state_sha256": digest(candidate) if candidate is not None else None,
            "errors": sorted(set(errors)),
            "production_database_touched": False,
            "decision": "HOLD",
            "authorization": "DENY",
        }

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._temp.cleanup()

    def __enter__(self) -> "DisposableSQLiteReplay":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class _InjectedRollback(Exception):
    pass
