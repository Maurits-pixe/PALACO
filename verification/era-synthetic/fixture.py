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


class Store:
    def __init__(self, path, source_commit):
        if type(source_commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            raise ValueError("a runner-supplied 40-hex source commit is required")
        if str(path) in ("", ":memory:"):
            raise ValueError("on-disk database required")
        self.source = {"repository": REPOSITORY, "commit": source_commit}
        self.db = sqlite3.connect(str(path), timeout=2, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=2000")
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS records (seq INTEGER PRIMARY KEY, body TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)")
            row = self.db.execute("SELECT source FROM metadata WHERE id=1").fetchone()
            if row is None:
                self.db.execute("INSERT INTO metadata VALUES (1,?)", (canonical(self.source).decode(),))
            elif not same(json.loads(row[0]), self.source):
                raise ValueError("source binding conflict")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def _records(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM records ORDER BY seq")]

    def _append(self, kind, data):
        records = self._records()
        if len(records) >= MAX_RECORDS:
            raise ValueError("record bound exceeded")
        previous = records[-1]["hash"] if records else digest(
            {"schema": SCHEMA, "source": self.source, "flags": FLAGS})
        body = {"seq": len(records) + 1, "kind": kind, "data": data, "prev": previous}
        record = {**body, "hash": digest(body)}
        self.db.execute("INSERT INTO records VALUES (?,?)",
                        (record["seq"], canonical(record).decode()))
        return record["hash"]

    def submit(self, value, *, _checkpoint=None):
        # Internal callable seam only: no CLI/input field can enable fault injection.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            key = value.get("request_key") if type(value) is dict else None
            if type(key) is str:
                old = self.db.execute("SELECT request_hash,receipt FROM requests WHERE key=?", (key,)).fetchone()
                if old:
                    if old[0] != digest(value):
                        raise ValueError("request key conflict")
                    self.db.commit()
                    return json.loads(old[1])
            validate_request(value)
            if any(r["kind"] == "revocation" for r in self._records()):
                raise ValueError("synthetic authority revoked")
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
            if not any(r["kind"] == "revocation" for r in self._records()):
                self._append("revocation", {"authority": FIXED["authority"], "execution": False})
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def export(self):
        self.db.execute("BEGIN")
        try:
            # Metadata and ordered log are read in the same SQLite snapshot.
            source = json.loads(self.db.execute("SELECT source FROM metadata WHERE id=1").fetchone()[0])
            body = {"schema": SCHEMA, "source": source, "flags": dict(FLAGS),
                    "records": self._records()}
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
