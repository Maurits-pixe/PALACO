"""Offline synthetic verification fixture; never grants execution authority."""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path

SCHEMA = "ERA_SYNTHETIC_V1"
REPOSITORY = "https://github.com/Maurits-pixe/PALACO"
FLAGS = {"synthetic_only": True, "execution": False, "release": False}
FIXED = {
    "identity": "synthetic-alice",
    "world": "WORLD-SYNTHETIC-1",
    "action": "record-fixture",
    "authority": "synthetic-recorder",
    "evidence": "fixture-observation-ok",
    "decision": "ALLOW_SYNTHETIC",
    "payload": {"fixture": "hello-era", "version": 1},
}
MAX_RECORDS = 1000
MAX_JSON_CHARS = 8192
MAX_JSON_BYTES = MAX_JSON_CHARS
_UNSET = object()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _publish_staged(directory, staged, name, checkpoint):
    if checkpoint is not None:
        checkpoint("before_publish")
    os.link(staged, name, src_dir_fd=directory, dst_dir_fd=directory,
            follow_symlinks=False)
    if checkpoint is not None:
        checkpoint("after_publish")
    os.fsync(directory)


def publish_envelope(path, envelope, *, _checkpoint=None):
    payload = canonical(envelope) + b"\n"
    path = Path(path)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    staged = None
    descriptor = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=".era-envelope-", suffix=".tmp", dir=path.parent)
        staged = Path(name).name
        with os.fdopen(descriptor, "wb") as output:
            descriptor = None
            if output.write(payload) != len(payload):
                raise OSError("incomplete envelope write")
            output.flush()
            os.fsync(output.fileno())
        _publish_staged(directory, staged, path.name, _checkpoint)
    finally:
        try:
            if descriptor is not None:
                os.close(descriptor)
            if staged is not None:
                os.unlink(staged, dir_fd=directory)
        finally:
            os.close(directory)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _validate_expected_proof(expected_proof):
    if expected_proof is not _UNSET and (
            type(expected_proof) is not str or
            not re.fullmatch(r"[0-9a-f]{64}", expected_proof)):
        raise ValueError("expected proof must be a lowercase 64-hex string")


def same(left, right):
    if type(left) is not type(right):
        return False
    if type(right) is dict:
        return left.keys() == right.keys() and all(same(left[k], v) for k, v in right.items())
    if type(right) is list:
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right


def request(key="demo-1"):
    return {"request_key": key, **json.loads(canonical(FIXED))}


def validate_request(value):
    if type(value) is not dict or value.keys() != FIXED.keys() | {"request_key"}:
        raise ValueError("unsupported request")
    key = value["request_key"]
    if type(key) is not str or not re.fullmatch(r"[a-z0-9-]{1,48}", key):
        raise ValueError("unsupported request key")
    if not same({k: value[k] for k in FIXED}, FIXED):
        raise ValueError("denied synthetic fixture")


def load_persisted(text, sql_type):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate persisted JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite persisted JSON")

    if sql_type != "text" or type(text) is not str or len(text) > MAX_JSON_CHARS:
        raise ValueError("invalid persisted JSON size or type")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid persisted JSON") from error


class Store:
    def __init__(self, path, source_commit, *, read_only=False):
        if type(read_only) is not bool:
            raise ValueError("read_only must be a bool")
        if type(source_commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            raise ValueError("a runner-supplied 40-hex source commit is required")
        if str(path) in ("", ":memory:"):
            raise ValueError("on-disk database required")
        self.source = {"repository": REPOSITORY, "commit": source_commit}
        self.read_only = read_only
        target = Path(path).absolute().as_uri() + "?mode=ro" if read_only else str(path)
        self.db = sqlite3.connect(target, timeout=2, isolation_level=None, uri=read_only)
        try:
            self.db.execute("PRAGMA busy_timeout=2000")
            if read_only:
                self.db.execute("PRAGMA query_only=ON")
                self.db.execute("BEGIN")
            else:
                self.db.execute("PRAGMA journal_mode=DELETE")
                self.db.execute("PRAGMA synchronous=FULL")
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL)")
                self.db.execute("CREATE TABLE IF NOT EXISTS records (seq INTEGER PRIMARY KEY, body TEXT NOT NULL)")
                self.db.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)")
                if not self.db.execute("SELECT 1 FROM metadata LIMIT 1").fetchone() and not (
                        self.db.execute("SELECT 1 FROM records LIMIT 1").fetchone() or
                        self.db.execute("SELECT 1 FROM requests LIMIT 1").fetchone()):
                    self.db.execute("INSERT INTO metadata VALUES (1,?)", (canonical(self.source).decode(),))
            self._validate_state()
            self.db.commit()
        except BaseException:
            try:
                self.db.rollback()
            finally:
                self.db.close()
            raise

    def close(self):
        self.db.close()

    def _records(self):
        rows = self.db.execute(
            "SELECT seq,CASE WHEN length(CAST(body AS BLOB)) <= ? THEN body END,"
            "typeof(body) FROM records ORDER BY seq LIMIT ?",
            (MAX_JSON_BYTES, MAX_RECORDS + 1)).fetchall()
        if len(rows) > MAX_RECORDS:
            raise ValueError("record bound exceeded")
        records = []
        for index, (seq, body, sql_type) in enumerate(rows, 1):
            record = load_persisted(body, sql_type)
            if (type(seq) is not int or seq != index or type(record) is not dict or
                    type(record.get("seq")) is not int or record["seq"] != seq):
                raise ValueError("persisted record sequence mismatch")
            records.append(record)
        return records

    def _validate_state(self):
        metadata = self.db.execute(
            "SELECT id,CASE WHEN length(CAST(source AS BLOB)) <= ? THEN source END,"
            "typeof(source) FROM metadata LIMIT 2",
            (MAX_JSON_BYTES,)).fetchall()
        if (len(metadata) != 1 or type(metadata[0][0]) is not int or
                metadata[0][0] != 1 or
                not same(load_persisted(*metadata[0][1:]), self.source)):
            raise ValueError("source binding conflict")
        records = self._records()
        previous = digest({"schema": SCHEMA, "source": self.source, "flags": FLAGS})
        expected = {}
        index = 0

        def consume(kind, data):
            nonlocal index, previous
            body = {"seq": index + 1, "kind": kind, "data": data, "prev": previous}
            record_hash = digest(body)
            if index >= len(records) or not same(records[index], {**body, "hash": record_hash}):
                raise ValueError("inconsistent persisted chain")
            index += 1
            previous = record_hash
            return record_hash

        while index < len(records):
            if records[index].get("kind") == "revocation":
                consume("revocation", {"authority": FIXED["authority"], "execution": False})
                if index != len(records):
                    raise ValueError("records after revocation")
                break
            data = records[index].get("data")
            if type(data) is not dict:
                raise ValueError("invalid persisted identity")
            value = request(data.get("request_key"))
            validate_request(value)
            key = value["request_key"]
            if key in expected:
                raise ValueError("duplicate persisted request key")
            identity = consume("identity", {"request_key": key, "identity": FIXED["identity"]})
            evidence = consume("evidence", {"identity": identity, "evidence": FIXED["evidence"]})
            decision = consume("decision", {"evidence": evidence, "decision": FIXED["decision"]})
            authorization = consume("authorization", {
                "decision": decision, "authority": FIXED["authority"], "execution": False})
            request_hash = digest(value)
            commit = consume("commit", {"authorization": authorization, "request": value,
                                        "request_hash": request_hash, "execution": False})
            expected[key] = (request_hash, {
                "commit": commit, "request_hash": request_hash,
                "historical_record_only": True, "execution": False})
        rows = self.db.execute(
            "SELECT CASE WHEN length(CAST(key AS BLOB)) <= ? THEN key END,"
            "CASE WHEN length(CAST(request_hash AS BLOB)) <= ? THEN request_hash END,"
            "CASE WHEN length(CAST(receipt AS BLOB)) <= ? THEN receipt END,"
            "typeof(key),typeof(request_hash),typeof(receipt) FROM requests LIMIT ?",
            (MAX_JSON_BYTES, MAX_JSON_BYTES, MAX_JSON_BYTES,
             MAX_RECORDS + 1)).fetchall()
        if len(rows) != len(expected):
            raise ValueError("persisted request mapping mismatch")
        for key, request_hash, receipt, key_type, hash_type, receipt_type in rows:
            if key_type != "text" or hash_type != "text" or key not in expected:
                raise ValueError("invalid persisted request row")
            expected_hash, expected_receipt = expected.pop(key)
            if request_hash != expected_hash or not same(
                    load_persisted(receipt, receipt_type), expected_receipt):
                raise ValueError("persisted receipt mismatch")
        return records

    def _append(self, kind, data):
        last = self.db.execute(
            "SELECT seq,CASE WHEN length(CAST(body AS BLOB)) <= ? THEN body END,"
            "typeof(body) FROM records ORDER BY seq DESC LIMIT 1",
            (MAX_JSON_BYTES,)).fetchone()
        count = last[0] if last else 0
        if count >= MAX_RECORDS:
            raise ValueError("record bound exceeded")
        previous = load_persisted(*last[1:])["hash"] if last else digest(
            {"schema": SCHEMA, "source": self.source, "flags": FLAGS})
        body = {"seq": count + 1, "kind": kind, "data": data, "prev": previous}
        record = {**body, "hash": digest(body)}
        self.db.execute("INSERT INTO records VALUES (?,?)",
                        (record["seq"], canonical(record).decode()))
        return record["hash"]

    def _check_expected_proof(self, records, expected_proof):
        body = {"schema": SCHEMA, "source": dict(self.source), "flags": dict(FLAGS),
                "records": records}
        envelope = {**body, "proof": {"algorithm": "SHA256", "digest": digest(body),
                                    "authenticity": False}}
        if expected_proof is not _UNSET and expected_proof != envelope["proof"]["digest"]:
            raise ValueError("expected proof mismatch")
        return envelope

    def submit(self, value, *, expected_proof=_UNSET, _checkpoint=None):
        if self.read_only:
            raise ValueError("read-only store permits export/backup/receipt lookup only")
        _validate_expected_proof(expected_proof)
        # Internal callable seam only: no CLI/input field can enable fault injection.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            records = self._validate_state()
            self._check_expected_proof(records, expected_proof)
            key = value.get("request_key") if type(value) is dict else None
            if type(key) is str:
                old = self.db.execute("SELECT request_hash,receipt FROM requests WHERE key=?", (key,)).fetchone()
                if old:
                    if old[0] != digest(value):
                        raise ValueError("request key conflict")
                    self.db.commit()
                    return load_persisted(old[1], "text")
            validate_request(value)
            if any(r["kind"] == "revocation" for r in records):
                raise ValueError("synthetic authority revoked")
            # Reserve a durable revocation slot before admitting a new five-record group.
            if len(records) + 5 + 1 > MAX_RECORDS:
                raise ValueError("record bound exceeded")
            identity = self._append("identity", {"request_key": key, "identity": value["identity"]})
            evidence = self._append("evidence", {"identity": identity, "evidence": value["evidence"]})
            decision = self._append("decision", {"evidence": evidence, "decision": "ALLOW_SYNTHETIC"})
            authorization = self._append("authorization", {
                "decision": decision, "authority": value["authority"], "execution": False})
            commit = self._append("commit", {
                "authorization": authorization, "request": value,
                "request_hash": digest(value), "execution": False})
            receipt = {"commit": commit, "request_hash": digest(value),
                       "historical_record_only": True, "execution": False}
            self.db.execute("INSERT INTO requests VALUES (?,?,?)",
                            (key, digest(value), canonical(receipt).decode()))
            if _checkpoint:
                _checkpoint("before_commit")
            self.db.commit()
            if _checkpoint:
                _checkpoint("after_commit")
            return receipt
        except BaseException:
            self.db.rollback()
            raise

    def revoke(self, *, expected_proof=_UNSET):
        if self.read_only:
            raise ValueError("read-only store permits export/backup/receipt lookup only")
        _validate_expected_proof(expected_proof)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            records = self._validate_state()
            self._check_expected_proof(records, expected_proof)
            if not any(r["kind"] == "revocation" for r in records):
                self._append("revocation", {"authority": FIXED["authority"], "execution": False})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def export(self, *, expected_proof=_UNSET):
        _validate_expected_proof(expected_proof)
        self.db.execute("BEGIN")
        try:
            # Metadata and ordered log are read in the same SQLite snapshot.
            records = self._validate_state()
            envelope = self._check_expected_proof(records, expected_proof)
            self.db.commit()
            return envelope
        except BaseException:
            self.db.rollback()
            raise

    def lookup_receipt(self, key, *, expected_proof):
        if not self.read_only:
            raise ValueError("receipt lookup requires a read-only store")
        if type(key) is not str or not re.fullmatch(r"[a-z0-9-]{1,48}", key):
            raise ValueError("unsupported request key")
        if (type(expected_proof) is not str or
                not re.fullmatch(r"[0-9a-f]{64}", expected_proof)):
            raise ValueError("expected proof must be a lowercase 64-hex string")
        self.db.execute("BEGIN")
        try:
            records = self._validate_state()
            self._check_expected_proof(records, expected_proof)
            row = self.db.execute(
                "SELECT receipt,typeof(receipt) FROM requests WHERE key=?", (key,)).fetchone()
            if row is None:
                raise ValueError("historical receipt not found")
            receipt = load_persisted(*row)
            self.db.commit()
            return receipt
        except BaseException:
            self.db.rollback()
            raise

    def backup(self, destination, *, expected_proof, _checkpoint=None):
        if not self.read_only:
            raise ValueError("backup requires a read-only store")
        if (type(expected_proof) is not str or
                not re.fullmatch(r"[0-9a-f]{64}", expected_proof)):
            raise ValueError("expected proof must be a lowercase 64-hex string")
        if self.db.in_transaction:
            raise ValueError("backup requires no active source transaction")
        path = Path(destination)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        staged = None
        descriptor = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=".era-backup-", suffix=".sqlite", dir=path.parent)
            staged = Path(name).name
            os.close(descriptor)
            descriptor = None
            deadline = time.monotonic() + 2

            def progress(status, remaining, total):
                if time.monotonic() >= deadline:
                    raise TimeoutError("synthetic backup exceeded two-second bound")

            target = sqlite3.connect(name, timeout=2, isolation_level=None)
            try:
                self.db.backup(target, pages=64, progress=progress, sleep=0.01)
                target.execute("PRAGMA journal_mode=DELETE")
            finally:
                target.close()
            reopened = Store(name, self.source["commit"], read_only=True)
            try:
                if reopened.db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("backup SQLite quick_check failed")
                envelope = reopened.export(expected_proof=expected_proof)
            finally:
                reopened.close()
            descriptor = os.open(name, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
                descriptor = None
            _publish_staged(directory, staged, path.name, _checkpoint)
            return {"result": "SYNTHETIC_BACKUP_VERIFIED",
                    "records": len(envelope["records"]), "proof": envelope["proof"]["digest"],
                    "source_commit": self.source["commit"],
                    "execution": False, "authenticity": False}
        finally:
            try:
                if descriptor is not None:
                    os.close(descriptor)
                if staged is not None:
                    for suffix in ("-journal", "-wal", "-shm", ""):
                        try:
                            os.unlink(staged + suffix, dir_fd=directory)
                        except FileNotFoundError:
                            pass
            finally:
                os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo", "export", "backup", "receipt"])
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--envelope", type=Path)
    parser.add_argument("--backup-db", type=Path)
    parser.add_argument("--request-key")
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--expected-proof", default=_UNSET)
    args = parser.parse_args()
    if args.command != "receipt" and (
            args.request_key is not None or args.receipt_output is not None):
        parser.error("--request-key and --receipt-output are only supported for receipt")
    if args.command == "receipt":
        if args.envelope is not None or args.backup_db is not None:
            parser.error("--envelope and --backup-db are not supported for receipt")
        if args.request_key is None or args.expected_proof is _UNSET:
            parser.error("receipt requires --request-key and --expected-proof")
        if not re.fullmatch(r"[a-z0-9-]{1,48}", args.request_key):
            parser.error("--request-key must match [a-z0-9-]{1,48}")
        if not re.fullmatch(r"[0-9a-f]{64}", args.expected_proof):
            parser.error("--expected-proof must be a lowercase 64-hex string")
    elif args.command == "backup":
        if args.envelope is not None:
            parser.error("--envelope is not supported for backup")
        if args.backup_db is None or args.expected_proof is _UNSET:
            parser.error("backup requires --backup-db and --expected-proof")
        if (type(args.expected_proof) is not str or
                not re.fullmatch(r"[0-9a-f]{64}", args.expected_proof)):
            parser.error("--expected-proof must be a lowercase 64-hex string")
    else:
        if args.backup_db is not None:
            parser.error("--backup-db is only supported for backup")
        if args.envelope is None:
            parser.error("--envelope is required for demo/export")
    if args.command == "demo" and args.expected_proof is not _UNSET:
        parser.error("--expected-proof is only supported for export/backup/receipt")
    if args.envelope is not None and (args.db.resolve() == args.envelope.resolve() or (
            args.db.exists() and args.envelope.exists() and args.db.samefile(args.envelope))):
        parser.error("database and envelope paths must differ")
    if args.receipt_output is not None and (
            args.db.resolve() == args.receipt_output.resolve() or (
                args.db.exists() and args.receipt_output.exists() and
                args.db.samefile(args.receipt_output))):
        parser.error("database and receipt paths must differ")
    store = Store(args.db, args.source_commit, read_only=args.command != "demo")
    try:
        if args.command == "receipt":
            receipt = store.lookup_receipt(args.request_key, expected_proof=args.expected_proof)
            if args.receipt_output is not None:
                publish_envelope(args.receipt_output, receipt)
            print(json.dumps({
                "result": "SYNTHETIC_HISTORICAL_RECEIPT", "request_key": args.request_key,
                "source_commit": args.source_commit, "proof": args.expected_proof,
                "receipt": receipt, "execution": False, "authenticity": False}))
            return
        if args.command == "backup":
            print(json.dumps(store.backup(args.backup_db, expected_proof=args.expected_proof)))
            return
        if args.command == "demo":
            receipt = store.submit(request())
            store.revoke()
            assert store.submit(request()) == receipt
        envelope = store.export(expected_proof=args.expected_proof)
        publish_envelope(args.envelope, envelope)
        result = {"result": "SYNTHETIC_ONLY", "records": len(envelope["records"]),
                  "proof": envelope["proof"]["digest"], "execution": False}
        if args.command == "export":
            result.update(result="SYNTHETIC_READ_ONLY_EXPORT", authenticity=False,
                          source_commit=envelope["source"]["commit"])
        print(json.dumps(result))
    finally:
        store.close()


if __name__ == "__main__":
    main()
