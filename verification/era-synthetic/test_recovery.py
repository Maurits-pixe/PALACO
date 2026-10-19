"""Persisted-state consistency regressions, not additional WF mappings."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import fixture

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40


class PersistedRecovery(unittest.TestCase):
    def setUp(self):
        work = HERE / ".runtime"
        work.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.directory.cleanup)
        self.counter = 0

    def fresh(self, committed=True):
        self.counter += 1
        path = Path(self.directory.name) / f"state-{self.counter}.sqlite"
        store = fixture.Store(path, SOURCE)
        if committed:
            store.submit(fixture.request())
        return path, store

    def snapshot(self, path):
        with sqlite3.connect(path) as db:
            rows = tuple(db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                         for table in ("metadata", "records", "requests"))
        return path.read_bytes(), rows

    def reject(self, mutate, *, committed=True):
        path, store = self.fresh(committed)
        try:
            with sqlite3.connect(path) as other:
                mutate(other)
            before = self.snapshot(path)
            for name, operation in (
                    ("retry", lambda: store.submit(fixture.request())),
                    ("fresh", lambda: store.submit(fixture.request("fresh"))),
                    ("revoke", store.revoke), ("export", store.export)):
                with self.subTest(operation=name):
                    with self.assertRaises(ValueError):
                        operation()
                    self.assertFalse(store.db.in_transaction)
                    self.assertEqual(self.snapshot(path), before)
        finally:
            store.close()
        connections = []
        connect = sqlite3.connect

        def capture(*args, **kwargs):
            db = connect(*args, **kwargs)
            connections.append(db)
            return db

        with patch.object(fixture.sqlite3, "connect", side_effect=capture):
            with self.assertRaises(ValueError):
                fixture.Store(path, SOURCE)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")
        self.assertEqual(self.snapshot(path), before)

    @staticmethod
    def records(db):
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM records ORDER BY seq")]

    @staticmethod
    def write_chain(db, records, *, sync_requests=True):
        previous = fixture.digest({"schema": fixture.SCHEMA,
                                   "source": {"repository": fixture.REPOSITORY, "commit": SOURCE},
                                   "flags": fixture.FLAGS})
        hashes = {}
        db.execute("DELETE FROM records")
        if sync_requests:
            db.execute("DELETE FROM requests")
        for index, record in enumerate(records, 1):
            old = record["hash"]
            for key in ("identity", "evidence", "decision", "authorization"):
                ref = record["data"].get(key)
                if type(ref) is str and ref in hashes:
                    record["data"][key] = hashes[ref]
            record["seq"], record["prev"] = index, previous
            record["hash"] = fixture.digest(
                {key: record[key] for key in ("seq", "kind", "data", "prev")})
            hashes[old] = previous = record["hash"]
            db.execute("INSERT INTO records VALUES (?,?)",
                       (index, fixture.canonical(record).decode()))
            if sync_requests and record["kind"] == "commit":
                value = record["data"]["request"]
                request_hash = fixture.digest(value)
                receipt = {"commit": record["hash"], "request_hash": request_hash,
                           "execution": False, "historical_record_only": True}
                db.execute("INSERT OR REPLACE INTO requests VALUES (?,?,?)",
                           (value["request_key"], request_hash, fixture.canonical(receipt).decode()))

    def test_valid_empty_revoked_only_and_committed_restarts(self):
        for state in ("empty", "revoked-only", "committed", "committed-revoked"):
            with self.subTest(state=state):
                path, store = self.fresh(state.startswith("committed"))
                try:
                    if "revoked" in state:
                        store.revoke()
                    envelope = store.export()
                finally:
                    store.close()
                store = fixture.Store(path, SOURCE)
                try:
                    self.assertEqual(store.export(), envelope)
                    if state.startswith("committed"):
                        receipt = store.submit(fixture.request())
                        self.assertIs(receipt["execution"], False)
                        self.assertIs(receipt["historical_record_only"], True)
                    elif state == "empty":
                        store.submit(fixture.request())
                    else:
                        with self.assertRaisesRegex(ValueError, "revoked"):
                            store.submit(fixture.request())
                finally:
                    store.close()

    def test_metadata_changed_or_missing_is_not_recreated(self):
        for sql, params in (
                ("DELETE FROM metadata", ()),
                ("UPDATE metadata SET source=?", (fixture.canonical(
                    {"repository": fixture.REPOSITORY, "commit": "b" * 40}).decode(),)),
                ("UPDATE metadata SET source=?", ("{}",))):
            with self.subTest(sql=sql, params=params):
                self.reject(lambda db: db.execute(sql, params))
        def requests_only(db):
            db.execute("DELETE FROM records")
            db.execute("DELETE FROM metadata")
        self.reject(requests_only)

    def test_metadata_cardinality_and_id(self):
        for ids in ((2,), (1, 2)):
            def mutate(db):
                db.execute("DROP TABLE metadata")
                db.execute("CREATE TABLE metadata (id INTEGER, source TEXT)")
                source = fixture.canonical(
                    {"repository": fixture.REPOSITORY, "commit": SOURCE}).decode()
                db.executemany("INSERT INTO metadata VALUES (?,?)", [(i, source) for i in ids])
            with self.subTest(ids=ids):
                self.reject(mutate)

    def test_missing_extra_and_changed_request_rows(self):
        for sql, params in (
                ("DELETE FROM requests", ()),
                ("INSERT INTO requests SELECT ?,request_hash,receipt FROM requests", ("extra",)),
                ("UPDATE requests SET key=?", ("different",)),
                ("UPDATE requests SET request_hash=?", ("0" * 64,)),
                ("UPDATE requests SET receipt=?", ("{}",))):
            with self.subTest(sql=sql):
                self.reject(lambda db: db.execute(sql, params))

    def test_forged_receipts_are_never_returned(self):
        for field, value in (("execution", True), ("execution", 0),
                             ("historical_record_only", False), ("historical_record_only", 1),
                             ("commit", "0" * 64), ("request_hash", "0" * 64),
                             ("extra", False)):
            def mutate(db):
                receipt = json.loads(db.execute("SELECT receipt FROM requests").fetchone()[0])
                receipt[field] = value
                db.execute("UPDATE requests SET receipt=?", (fixture.canonical(receipt).decode(),))
            with self.subTest(field=field, value=value):
                self.reject(mutate)

    def test_sql_sequence_gap_and_json_divergence(self):
        self.reject(lambda db: db.execute("UPDATE records SET seq=9 WHERE seq=5"))
        for value in (2, True, 1.0, "1"):
            def mutate(db):
                records = self.records(db)
                records[0]["seq"] = value
                records[0]["hash"] = fixture.digest(
                    {key: records[0][key] for key in ("seq", "kind", "data", "prev")})
                db.execute("UPDATE records SET body=? WHERE seq=1",
                           (fixture.canonical(records[0]).decode(),))
            with self.subTest(value=value):
                self.reject(mutate)

    def test_partial_corrupt_and_reordered_chains(self):
        for seq in range(1, 6):
            with self.subTest(missing=seq):
                self.reject(lambda db: db.execute("DELETE FROM records WHERE seq=?", (seq,)))
        for field, value in (("hash", "0" * 64), ("prev", "0" * 64),
                             ("kind", "unknown"), ("data", []), ("extra", False)):
            def mutate(db):
                records = self.records(db)
                records[0][field] = value
                db.execute("UPDATE records SET body=? WHERE seq=1",
                           (fixture.canonical(records[0]).decode(),))
            with self.subTest(field=field):
                self.reject(mutate)
        def reorder(db):
            records = self.records(db)
            records[0], records[1] = records[1], records[0]
            self.write_chain(db, records)
        self.reject(reorder)

    def test_rehashed_wrong_fixed_data_references_and_request_hashes(self):
        cases = (
            (0, "identity", "other"), (1, "identity", "0" * 64),
            (1, "evidence", "other"), (2, "evidence", "0" * 64),
            (2, "decision", "EXECUTE"), (3, "decision", "0" * 64),
            (3, "authority", "other"), (3, "execution", True),
            (4, "authorization", "0" * 64), (4, "request_hash", "0" * 64),
            (4, "execution", 0))
        for index, field, value in cases:
            def mutate(db):
                records = self.records(db)
                records[index]["data"][field] = value
                self.write_chain(db, records)
            with self.subTest(index=index, field=field):
                self.reject(mutate)

    def test_rehashed_wrong_request_types_and_fields(self):
        for field, value in (("world", "other"), ("action", "other"),
                             ("payload", {"fixture": "hello-era", "version": True}),
                             ("payload", {"fixture": "hello-era", "version": 1.0}),
                             ("identity", "other"), ("decision", "DENY"),
                             ("request_key", "different")):
            def mutate(db):
                records = self.records(db)
                value_in_log = records[4]["data"]["request"]
                value_in_log[field] = value
                records[4]["data"]["request_hash"] = fixture.digest(value_in_log)
                self.write_chain(db, records)
            with self.subTest(field=field, value=value):
                self.reject(mutate)

    def test_duplicate_request_keys_and_terminal_revocation_rule(self):
        def duplicate(db):
            records = self.records(db)
            self.write_chain(db, records + copy.deepcopy(records))
        self.reject(duplicate)
        for location in ("before", "twice", "wrong"):
            def mutate(db):
                records = self.records(db)
                revocation = {"seq": 0, "kind": "revocation", "hash": "old", "prev": "",
                              "data": {"authority": fixture.FIXED["authority"], "execution": False}}
                if location == "before":
                    records.insert(0, revocation)
                else:
                    records.append(revocation)
                    if location == "twice":
                        records.append(copy.deepcopy(revocation))
                    else:
                        revocation["data"]["execution"] = 0
                self.write_chain(db, records)
            with self.subTest(location=location):
                self.reject(mutate)

    def test_strict_bounded_json_for_every_persisted_json_column(self):
        invalid = ('{', 'null', '[]', 'true', '{"x":NaN}', '{"x":Infinity}',
                   '{"x":-Infinity}', '{"x":1,"x":1}', "[" * 2000 + "]" * 2000,
                   " " * (fixture.MAX_JSON_CHARS + 1), '{"x":' + "9" * 5000 + "}",
                   sqlite3.Binary(b"\xff"), 12)
        for table, column in (("metadata", "source"), ("records", "body"),
                              ("requests", "receipt")):
            for raw in invalid:
                with self.subTest(table=table, raw=str(raw)[:40]):
                    self.reject(lambda db: db.execute(
                        f"UPDATE {table} SET {column}=?", (raw,)))
        def nested_duplicate(db):
            body = db.execute("SELECT body FROM records WHERE seq=5").fetchone()[0]
            db.execute("UPDATE records SET body=? WHERE seq=5",
                       (body.replace('"version":1', '"version":1,"version":1'),))
        self.reject(nested_duplicate)

    def test_record_bound_includes_existing_state(self):
        path, store = self.fresh()
        try:
            with patch.object(fixture, "MAX_RECORDS", 4):
                before = self.snapshot(path)
                for operation in (store.export, store.revoke,
                                  lambda: store.submit(fixture.request())):
                    with self.assertRaisesRegex(ValueError, "record bound exceeded"):
                        operation()
                    self.assertEqual(self.snapshot(path), before)
                with self.assertRaisesRegex(ValueError, "record bound exceeded"):
                    fixture.Store(path, SOURCE)
                self.assertEqual(self.snapshot(path), before)
        finally:
            store.close()

    def test_coherent_suffix_removal_is_not_rollback_detection(self):
        path, store = self.fresh()
        try:
            first = store.submit(fixture.request())
            store.submit(fixture.request("second"))
            store.revoke()
            original_proof = store.export()["proof"]["digest"]
            with sqlite3.connect(path) as other:
                other.execute("DELETE FROM records WHERE seq>5")
                other.execute("DELETE FROM requests WHERE key=?", ("second",))
            self.assertNotEqual(store.export()["proof"]["digest"], original_proof)
            self.assertEqual(store.submit(fixture.request()), first)
        finally:
            store.close()
        store = fixture.Store(path, SOURCE)
        try:
            self.assertEqual(len(store.export()["records"]), 5)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
