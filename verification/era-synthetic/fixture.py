"""Offline synthetic verification fixture; never grants execution authority."""
import argparse
import hashlib
import json
import re
import sqlite3
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


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


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
    def __init__(self, path, source_commit):
        if type(source_commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            raise ValueError("a runner-supplied 40-hex source commit is required")
        if str(path) in ("", ":memory:"):
            raise ValueError("on-disk database required")
        self.source = {"repository": REPOSITORY, "commit": source_commit}
        self.db = sqlite3.connect(str(path), timeout=2, isolation_level=None)
        try:
            self.db.execute("PRAGMA busy_timeout=2000")
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
            self.db.rollback()
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def _records(self):
        rows = self.db.execute(
            "SELECT seq,substr(body,1,?),typeof(body) FROM records ORDER BY seq LIMIT ?",
            (MAX_JSON_CHARS + 1, MAX_RECORDS + 1)).fetchall()
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
            "SELECT id,substr(source,1,?),typeof(source) FROM metadata LIMIT 2",
            (MAX_JSON_CHARS + 1,)).fetchall()
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
            "SELECT substr(key,1,?),substr(request_hash,1,?),substr(receipt,1,?),"
            "typeof(key),typeof(request_hash),typeof(receipt) FROM requests LIMIT ?",
            (MAX_JSON_CHARS + 1, MAX_JSON_CHARS + 1, MAX_JSON_CHARS + 1,
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
            "SELECT seq,substr(body,1,?),typeof(body) FROM records ORDER BY seq DESC LIMIT 1",
            (MAX_JSON_CHARS + 1,)).fetchone()
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

    def submit(self, value, *, _checkpoint=None):
        # Internal callable seam only: no CLI/input field can enable fault injection.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            records = self._validate_state()
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

    def revoke(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            records = self._validate_state()
            if not any(r["kind"] == "revocation" for r in records):
                self._append("revocation", {"authority": FIXED["authority"], "execution": False})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def export(self):
        self.db.execute("BEGIN")
        try:
            # Metadata and ordered log are read in the same SQLite snapshot.
            records = self._validate_state()
            body = {"schema": SCHEMA, "source": dict(self.source), "flags": dict(FLAGS),
                    "records": records}
            envelope = {**body, "proof": {"algorithm": "SHA256", "digest": digest(body),
                                        "authenticity": False}}
            self.db.commit()
            return envelope
        except BaseException:
            self.db.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo"])
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--envelope", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    if args.db.resolve() == args.envelope.resolve():
        parser.error("database and envelope paths must differ")
    store = Store(args.db, args.source_commit)
    try:
        receipt = store.submit(request())
        store.revoke()
        assert store.submit(request()) == receipt
        envelope = store.export()
        # Exclusive creation avoids overwriting caller inputs, including the database.
        with args.envelope.open("x", encoding="ascii") as output:
            output.write(canonical(envelope).decode() + "\n")
        print(json.dumps({"result": "SYNTHETIC_ONLY", "records": len(envelope["records"]),
                          "proof": envelope["proof"]["digest"], "execution": False}))
    finally:
        store.close()


if __name__ == "__main__":
    main()
