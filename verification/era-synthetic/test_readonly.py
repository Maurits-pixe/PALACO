"""Read-only inspection regressions, not additional WF mappings or WAL guarantees."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fixture

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40


class ReadOnlyInspection(unittest.TestCase):
    def setUp(self):
        work = HERE / ".runtime"
        work.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.db = self.path / "state.sqlite"
        self.output = self.path / "export.json"
        self.seed()

    def seed(self, *, path=None, committed=True, revoked=False):
        store = fixture.Store(path or self.db, SOURCE)
        try:
            if committed:
                store.submit(fixture.request())
            if revoked:
                store.revoke()
            return store.export()
        finally:
            store.close()

    def reader(self, path=None):
        store = fixture.Store(path or self.db, SOURCE, read_only=True)
        self.addCleanup(store.close)
        return store

    def snapshot(self, path=None):
        path = path or self.db
        with sqlite3.connect(path) as db:
            schema = db.execute("SELECT * FROM sqlite_schema ORDER BY name").fetchall()
            rows = [db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in ("metadata", "records", "requests")]
        return path.read_bytes(), path.stat().st_mtime_ns, schema, rows

    def cli(self, *extra, command="export", db=None, output=None, source=SOURCE,
            accepted=True):
        result = subprocess.run(
            [sys.executable, "-I", str(HERE / "fixture.py"), command,
             "--db", str(db or self.db), "--envelope", str(output or self.output),
             "--source-commit", source, *extra],
            capture_output=True, text=True, timeout=10)
        if accepted:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_main_file_schema_and_rows_unchanged(self):
        before = self.snapshot()
        store = self.reader()
        traces = []
        store.db.set_trace_callback(traces.append)
        first = store.export()
        self.assertEqual(len(first["records"]), 5)
        self.assertEqual(store.export(), first)
        for operation in (lambda: store.submit(fixture.request()), store.revoke):
            with self.assertRaisesRegex(ValueError, "read-only"):
                operation()
        self.assertFalse(store.db.in_transaction)
        store.close()
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("BEGIN IMMEDIATE", traces)

    def test_constructor_only_reads_and_uses_bounded_timeout(self):
        connect = sqlite3.connect
        traces = []

        def capture(*args, **kwargs):
            self.assertEqual(args[0], self.db.absolute().as_uri() + "?mode=ro")
            self.assertIs(kwargs["uri"], True)
            db = connect(*args, **kwargs)
            db.set_trace_callback(traces.append)
            return db

        with patch.object(fixture.sqlite3, "connect", side_effect=capture):
            store = self.reader()
        self.assertEqual(store.db.execute("PRAGMA busy_timeout").fetchone(), (2000,))
        self.assertEqual(store.db.execute("PRAGMA query_only").fetchone(), (1,))
        self.assertEqual(store.db.execute("PRAGMA read_uncommitted").fetchone(), (0,))
        self.assertIn("BEGIN", traces)
        self.assertIn("COMMIT", traces)
        for statement in traces:
            self.assertFalse(any(token in statement.upper() for token in
                                 ("JOURNAL_MODE", "SYNCHRONOUS", "CREATE", "INSERT",
                                  "IMMUTABLE", "BEGIN IMMEDIATE")))

    def test_strict_boolean_flag_and_keyword_only(self):
        for value in (None, 0, 1, "", "false", [], object()):
            with self.subTest(value=value):
                with patch.object(fixture.sqlite3, "connect") as connect:
                    with self.assertRaises(ValueError):
                        fixture.Store(self.db, SOURCE, read_only=value)
                    connect.assert_not_called()
        with self.assertRaises(TypeError):
            fixture.Store(self.db, SOURCE, True)

    def test_api_denies_all_writes_before_database_access(self):
        self.seed(revoked=True)
        store = self.reader()
        store.close()
        for value in (fixture.request(), fixture.request("new"), None):
            with self.assertRaisesRegex(ValueError, "read-only"):
                store.submit(value)
        with self.assertRaisesRegex(ValueError, "read-only"):
            store.revoke()

    def test_sqlite_itself_denies_raw_and_internal_writes(self):
        before = self.snapshot()
        store = self.reader()
        for sql in ("DELETE FROM records", "CREATE TABLE forbidden (x)",
                    "UPDATE metadata SET source='{}'"):
            with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                store.db.execute(sql)
        with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
            store._append("revocation", {"authority": fixture.FIXED["authority"],
                                         "execution": False})
        store.db.execute("PRAGMA query_only=OFF")
        with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
            store.db.execute("DELETE FROM records")
        self.assertEqual(self.snapshot(), before)

    def test_missing_database_never_created(self):
        path = self.path / "missing.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            fixture.Store(path, SOURCE, read_only=True)
        self.assertFalse(path.exists())
        self.cli(db=path, accepted=False)
        self.assertFalse(path.exists())
        self.assertFalse(self.output.exists())

    def test_missing_schema_and_zero_length_never_initialized(self):
        for name, initialized in (("zero.sqlite", False), ("partial.sqlite", True)):
            with self.subTest(name=name):
                path = self.path / name
                path.touch()
                if initialized:
                    with sqlite3.connect(path) as db:
                        db.execute("CREATE TABLE records (seq INTEGER PRIMARY KEY, body TEXT)")
                before = path.read_bytes(), path.stat().st_mtime_ns
                with self.assertRaises(sqlite3.DatabaseError):
                    fixture.Store(path, SOURCE, read_only=True)
                self.cli(db=path, accepted=False)
                self.assertFalse(self.output.exists())
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_failed_validation_closes_connection_and_rolls_back(self):
        connect = sqlite3.connect
        connections = []

        def capture(*args, **kwargs):
            db = connect(*args, **kwargs)
            connections.append(db)
            return db

        before = self.snapshot()
        with patch.object(fixture.sqlite3, "connect", side_effect=capture):
            with self.assertRaisesRegex(ValueError, "source binding"):
                fixture.Store(self.db, "b" * 40, read_only=True)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")
        with sqlite3.connect(self.db, timeout=0) as db:
            db.execute("BEGIN EXCLUSIVE")
        self.assertEqual(self.snapshot(), before)

    def test_source_and_corruption_reject_without_output_or_repair(self):
        self.cli(source="b" * 40, accepted=False)
        self.assertFalse(self.output.exists())
        for sql, values in (
                ("UPDATE records SET body=? WHERE seq=1", ("{}\x00",)),
                ("UPDATE records SET body=? WHERE seq=1", ('{"seq":true}',)),
                ("DELETE FROM requests", ()),
                ("DELETE FROM metadata", ())):
            with self.subTest(sql=sql, values=values):
                path = self.path / ("bad-" + str(len(list(self.path.iterdir()))) + ".sqlite")
                self.seed(path=path)
                with sqlite3.connect(path) as db:
                    db.execute(sql, values)
                before = self.snapshot(path)
                with self.assertRaises(ValueError):
                    fixture.Store(path, SOURCE, read_only=True)
                self.cli(db=path, accepted=False)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.snapshot(path), before)

    def test_literal_uri_special_characters_and_uri_looking_names(self):
        for name in ("question?mode=rw.sqlite", "hash#part.sqlite", "percent%3f.sqlite",
                     "file:other.sqlite?mode=rwc#%25", "file::memory:?cache=shared"):
            with self.subTest(name=name):
                path = self.path / name
                expected = self.seed(path=path)
                before = self.snapshot(path)
                self.assertEqual(self.reader(path).export(), expected)
                self.assertEqual(self.snapshot(path), before)
                self.cli(db=path, output=self.path / (name + ".json"))
        self.assertFalse((self.path / "other.sqlite").exists())

    def test_relative_literal_path_is_made_absolute(self):
        relative = self.db.relative_to(Path.cwd())
        self.assertEqual(self.reader(relative).export(), self.reader().export())

    def test_each_export_revalidates_second_connection_changes(self):
        store = self.reader()
        expected = store.export()
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE records SET body=body || char(0) WHERE seq=1")
        before = self.snapshot()
        for _ in range(2):
            with self.assertRaises(ValueError):
                store.export(expected_proof=expected["proof"]["digest"])
            self.assertFalse(store.db.in_transaction)
            self.assertEqual(self.snapshot(), before)

    def test_reader_observes_commits_not_uncommitted_writes(self):
        store = self.reader()
        expected = store.export()
        other = sqlite3.connect(self.db, isolation_level=None)
        self.addCleanup(other.close)
        other.execute("BEGIN IMMEDIATE")
        other.execute("UPDATE records SET body='{}' WHERE seq=1")
        self.assertEqual(store.export(), expected)
        other.commit()
        with self.assertRaises(ValueError):
            store.export()

    def test_readonly_does_not_disable_sqlite_locking(self):
        store = self.reader()
        other = sqlite3.connect(self.db, isolation_level=None)
        self.addCleanup(other.close)
        other.execute("BEGIN EXCLUSIVE")
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                store.export()
            self.assertFalse(store.db.in_transaction)
        finally:
            other.rollback()
        self.assertEqual(len(store.export()["records"]), 5)

    def test_empty_and_revoked_only_stores_export_but_checker_rejects(self):
        for revoked in (False, True):
            path = self.path / f"empty-{revoked}.sqlite"
            expected = self.seed(path=path, committed=False, revoked=revoked)
            before = self.snapshot(path)
            envelope = self.reader(path).export()
            self.assertEqual(envelope, expected)
            self.assertEqual(len(envelope["records"]), int(revoked))
            output = self.path / f"empty-{revoked}.json"
            self.cli(db=path, output=output)
            result = subprocess.run(
                [sys.executable, "-I", str(HERE / "verify.py"), str(output)],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(self.snapshot(path), before)

    def test_api_expected_proof_strict_validation_and_default(self):
        class Text(str):
            pass

        store = self.reader()
        expected = store.export()
        proof = expected["proof"]["digest"]
        self.assertEqual(store.export(expected_proof=proof), expected)
        for value in (None, False, 0, [], {}, Text(proof), "", "a" * 63,
                      "a" * 65, "A" * 64, "g" * 64, proof + "\n", "0" * 64):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    store.export(expected_proof=value)
                self.assertFalse(store.db.in_transaction)
        self.assertEqual(store.export(), expected)

    def test_cli_nonrevoked_export_repeated_proof_and_explicit_status(self):
        before = self.snapshot()
        first = self.cli()
        second_path = self.path / "second.json"
        second = self.cli(output=second_path)
        self.assertEqual(first, second)
        self.assertEqual(self.output.read_bytes(), second_path.read_bytes())
        self.assertEqual(first, {
            "result": "SYNTHETIC_READ_ONLY_EXPORT", "records": 5,
            "source_commit": SOURCE, "execution": False, "authenticity": False,
            "proof": self.reader().export()["proof"]["digest"]})
        self.assertNotIn("revocation", [r["kind"] for r in
                                     json.loads(self.output.read_text())["records"]])
        self.assertEqual(self.snapshot(), before)

    def test_cli_matching_malformed_and_mismatched_proof(self):
        proof = self.reader().export()["proof"]["digest"]
        before = self.snapshot()
        for value in ("", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "0" * 64):
            with self.subTest(value=value):
                self.cli("--expected-proof", value, accepted=False)
                self.assertFalse(self.output.exists())
                self.assertEqual(self.snapshot(), before)
        result = self.cli("--expected-proof", proof)
        self.assertEqual(result["proof"], proof)
        self.assertEqual(self.snapshot(), before)

    def test_coherent_suffix_removal_requires_trusted_original_anchor(self):
        store = fixture.Store(self.db, SOURCE)
        try:
            store.submit(fixture.request("second"))
            store.revoke()
            original = store.export()["proof"]["digest"]
        finally:
            store.close()
        reader = self.reader()
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM records WHERE seq>5")
            db.execute("DELETE FROM requests WHERE key='second'")
        before = self.snapshot()
        changed = reader.export()
        self.assertNotEqual(changed["proof"]["digest"], original)
        with self.assertRaisesRegex(ValueError, "expected proof mismatch"):
            reader.export(expected_proof=original)
        self.cli("--expected-proof", original, accepted=False)
        self.assertFalse(self.output.exists())
        unanchored = self.cli()
        self.assertEqual(unanchored["proof"], changed["proof"]["digest"])
        # An attacker-supplied new digest is not a trusted original anchor.
        self.cli("--expected-proof", changed["proof"]["digest"],
                 output=self.path / "rehashed.json")
        self.assertEqual(self.snapshot(), before)

    def test_rehashed_invalid_chain_still_rejects_matching_anchor(self):
        envelope = self.reader().export()
        envelope["records"][0]["data"]["identity"] = "not-synthetic-alice"
        previous = fixture.digest({k: envelope[k] for k in ("schema", "source", "flags")})
        with sqlite3.connect(self.db) as db:
            for record in envelope["records"]:
                record["prev"] = previous
                record["hash"] = fixture.digest(
                    {k: record[k] for k in ("seq", "kind", "data", "prev")})
                previous = record["hash"]
                db.execute("UPDATE records SET body=? WHERE seq=?",
                           (fixture.canonical(record).decode(), record["seq"]))
        proof = fixture.digest({k: envelope[k] for k in ("schema", "source", "flags", "records")})
        before = self.snapshot()
        self.cli("--expected-proof", proof, accepted=False)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.snapshot(), before)

    def test_cli_no_overwrite_or_database_alias_mutation(self):
        before = self.snapshot()
        self.output.write_text("caller-owned")
        self.cli(accepted=False)
        self.assertEqual(self.output.read_text(), "caller-owned")
        self.cli(output=self.db, accepted=False)
        alias = self.path / "alias.sqlite"
        alias.hardlink_to(self.db)
        self.cli(output=alias, accepted=False)
        symlink = self.path / "symlink.sqlite"
        symlink.symlink_to(self.db)
        self.cli(output=symlink, accepted=False)
        self.assertEqual(self.snapshot(), before)

    def test_demo_rejects_export_only_flag_before_any_mutation(self):
        before = self.snapshot()
        for proof in ("a" * 64, "bad"):
            self.cli("--expected-proof", proof, command="demo", accepted=False)
            self.assertFalse(self.output.exists())
            self.assertEqual(self.snapshot(), before)
        missing = self.path / "demo-missing.sqlite"
        self.cli("--expected-proof", "a" * 64, command="demo", db=missing, accepted=False)
        self.assertFalse(missing.exists())

    def test_default_demo_repeats_legacy_behavior(self):
        first = self.cli(command="demo")
        before = self.snapshot()
        second = self.cli(command="demo", output=self.path / "repeat.json")
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"result", "records", "proof", "execution"})
        self.assertEqual(first["result"], "SYNTHETIC_ONLY")
        self.assertEqual(first["records"], 6)
        self.assertIs(first["execution"], False)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
