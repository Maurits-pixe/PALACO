#!/usr/bin/env python3
"""GO-20 v49: disposable SQLite challenge lifecycle ledger.

A transactional, locally durable test model: UNIQUE nonce, atomic
ISSUED->CONSUMED, explicit expiry, no replay or concurrent double-consume.
Never a production admission service or proof of independently trusted time.
The caller MUST provide full v48 sources; no caller-supplied approval booleans.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from pr_audit_integrity import canonical_hash, is_hex
from pr_archive_availability_challenge import assess as assess_v48

DDL = """
CREATE TABLE IF NOT EXISTS challenge_ledger(
  nonce_sha256 TEXT PRIMARY KEY NOT NULL,
  challenge_sha256 TEXT UNIQUE NOT NULL,
  issued_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  consumed_at INTEGER,
  state TEXT NOT NULL CHECK(state IN ('ISSUED','CONSUMED')),
  CHECK(expires_at > issued_at),
  CHECK((state = 'ISSUED' AND consumed_at IS NULL) OR
        (state = 'CONSUMED' AND consumed_at IS NOT NULL))
);
"""


def verdict(status, errors=()):
    return {
        "schema": "palaco.go20-challenge-lifecycle-verdict.v1",
        "status": status,
        "errors": list(errors),
        "decision": "HOLD", "authorization": "DENY",
        "production_commit_performed": False,
        "remote_availability_verified": False,
        "recovery_authorized": False,
        "merge_authorized": False, "deployment_authorized": False,
    }


class ChallengeLedger:
    def __init__(self, database: str | Path):
        # Only test-owned, explicit file handles. Reject URI, in-memory or
        # accidental implicit global DB. CI uses TemporaryDirectory.
        location = str(database)
        if (not location or location == ":memory:" or location.startswith("file:") or
                not Path(location).is_absolute() or not Path(location).parent.is_dir()):
            raise ValueError("explicit_absolute_test_database_required")
        self.database = location
        with self._connect() as db:
            db.executescript(DDL)

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _valid_challenge(challenge, pin):
        return (
            isinstance(challenge, dict) and
            set(challenge) == {"schema", "nonce_sha256", "chain_sha256",
                               "sequence", "minimum_response_count"} and
            challenge.get("schema") == "palaco.go20-archive-availability-challenge.v1" and
            is_hex(challenge.get("nonce_sha256"), 64) and
            is_hex(challenge.get("chain_sha256"), 64) and
            type(challenge.get("sequence")) is int and challenge["sequence"] >= 0 and
            type(challenge.get("minimum_response_count")) is int and
            challenge["minimum_response_count"] >= 2 and
            isinstance(pin, dict) and
            pin.get("schema") == "palaco.go20-archive-availability-challenge-pin.v1" and
            pin.get("challenge_sha256") == canonical_hash(challenge) and
            pin.get("trusted_chain_sha256") == challenge["chain_sha256"] and
            type(pin.get("minimum_sequence")) is int and
            challenge["sequence"] >= pin["minimum_sequence"] and
            type(pin.get("minimum_responses")) is int and
            pin["minimum_responses"] >= 2
        )

    def issue(self, challenge, pin, issued_at: int, expires_at: int, now: int):
        if (not self._valid_challenge(challenge, pin) or
                any(type(v) is not int or v < 0 for v in (issued_at, expires_at, now)) or
                issued_at != now or expires_at <= now or expires_at - issued_at > 3600):
            return verdict("DENIED", ("invalid_or_expired_issue",))
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO challenge_ledger(nonce_sha256,challenge_sha256,issued_at,"
                "expires_at,state) VALUES(?,?,?,?,?)",
                (challenge["nonce_sha256"], canonical_hash(challenge),
                 issued_at, expires_at, "ISSUED"))
            db.execute("COMMIT")
            return verdict("ISSUED_TEST_ONLY")
        except sqlite3.IntegrityError:
            db.execute("ROLLBACK")
            return verdict("DENIED", ("duplicate_nonce_or_challenge",))
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def consume(self, challenge, pin, v48_sources: dict, now: int):
        if (not self._valid_challenge(challenge, pin) or
                type(now) is not int or now < 0 or
                not isinstance(v48_sources, dict) or
                set(v48_sources) != {"chain", "chain_pin", "witnesses", "v45",
                    "archive", "custodians", "retention_pin", "responses"}):
            return verdict("DENIED", ("invalid_consume_arguments",))
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT challenge_sha256,issued_at,expires_at,state "
                             "FROM challenge_ledger WHERE nonce_sha256=?",
                             (challenge["nonce_sha256"],)).fetchone()
            if row is None:
                return verdict("DENIED", ("challenge_not_issued",))
            digest, issued_at, expires_at, state = row
            if digest != canonical_hash(challenge):
                return verdict("DENIED", ("nonce_reused_with_different_challenge",))
            if state != "ISSUED":
                return verdict("DENIED", ("challenge_already_consumed",))
            if not issued_at <= now < expires_at:
                return verdict("DENIED", ("challenge_expired_or_clock_rollback",))
            try:
                evidence = assess_v48(
                    v48_sources["chain"], v48_sources["chain_pin"],
                    v48_sources["witnesses"], v48_sources["v45"],
                    v48_sources["archive"], v48_sources["custodians"],
                    v48_sources["retention_pin"], challenge,
                    v48_sources["responses"], pin)
            except (ValueError, TypeError, KeyError, IndexError,
                    AttributeError, OverflowError, RecursionError, MemoryError):
                return verdict("DENIED", ("invalid_v48_evidence",))
            if not evidence["challenge_evidence_valid"]:
                return verdict("DENIED", ("v48_evidence_invalid",))
            updated = db.execute(
                "UPDATE challenge_ledger SET state='CONSUMED',consumed_at=? "
                "WHERE nonce_sha256=? AND state='ISSUED'",
                (now, challenge["nonce_sha256"])).rowcount
            if updated != 1:
                return verdict("DENIED", ("concurrent_consume_lost",))
            db.execute("COMMIT")
            return verdict("CONSUMED_TEST_ONLY")
        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")
            db.close()

    def inspect(self, nonce_sha256: str):
        if not is_hex(nonce_sha256, 64):
            return None
        with self._connect() as db:
            return db.execute(
                "SELECT state,issued_at,expires_at,consumed_at "
                "FROM challenge_ledger WHERE nonce_sha256=?",
                (nonce_sha256,)).fetchone()
