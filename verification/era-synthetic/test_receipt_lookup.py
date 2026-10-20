"""Synthetic read-only receipt recovery; no additional official WF mappings."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import fixture

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40  # Artificial source binding for this synthetic fixture only.


class ReceiptLookup(unittest.TestCase):
    def setUp(self):
        runtime = HERE / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.path = self.work / "state.sqlite"
        self.output = self.work / "receipt.json"
        store = fixture.Store(self.path, SOURCE)
        try:
            self.receipt = store.submit(fixture.request())
            self.envelope = store.export()
        finally:
            store.close()
        self.proof = self.envelope["proof"]["digest"]

    def reader(self):
        store = fixture.Store(self.path, SOURCE, read_only=True)
        self.addCleanup(store.close)
        return store

    def snapshot(self):
        with sqlite3.connect(self.path) as db:
            schema = db.execute("SELECT * FROM sqlite_schema ORDER BY name").fetchall()
            rows = [db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in ("metadata", "records", "requests")]
        return self.path.read_bytes(), self.path.stat().st_mtime_ns, schema, rows

    def cli(self, *extra, command="receipt", db=None, key="demo-1", proof=None):
        args = [sys.executable, "-I", str(HERE / "fixture.py"), command,
                "--db", str(self.path if db is None else db), "--source-commit", SOURCE]
        if key is not None:
            args += ["--request-key", key]
        if proof is not None:
            args += ["--expected-proof", proof]
        result = subprocess.run(args + list(extra), capture_output=True, text=True, timeout=10)
        return result

    def rejected(self, result, message=None):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        if message:
            self.assertIn(message, result.stderr)

    def test_exact_original_receipt_before_after_revocation_and_restart(self):
        before = self.snapshot()
        with patch.object(fixture.Store, "submit", side_effect=AssertionError("no replay")):
            store = self.reader()
            found = store.lookup_receipt("demo-1", expected_proof=self.proof)
            self.assertTrue(fixture.same(found, self.receipt))
            found["execution"] = True
            self.assertTrue(fixture.same(
                store.lookup_receipt("demo-1", expected_proof=self.proof), self.receipt))
            store.close()
        self.assertEqual(before, self.snapshot())
        writer = fixture.Store(self.path, SOURCE)
        writer.revoke()
        envelope = writer.export()
        writer.close()
        before = self.snapshot()
        with patch.object(fixture.Store, "submit", side_effect=AssertionError("no replay")):
            for _ in range(2):
                store = self.reader()
                self.assertTrue(fixture.same(store.lookup_receipt(
                    "demo-1", expected_proof=envelope["proof"]["digest"]), self.receipt))
                store.close()
        self.assertEqual(before, self.snapshot())

    def test_read_only_sql_snapshot_and_unchanged_success_and_errors(self):
        before = self.snapshot()
        store = self.reader()
        trace = []
        store.db.set_trace_callback(trace.append)
        changes = store.db.total_changes
        with patch.object(store, "_validate_state", wraps=store._validate_state) as validate:
            self.assertTrue(fixture.same(
                store.lookup_receipt("demo-1", expected_proof=self.proof), self.receipt))
            self.assertEqual(validate.call_count, 1)
        self.assertEqual(trace[0], "BEGIN")
        self.assertEqual(trace[-1], "COMMIT")
        self.assertTrue(trace[-2].startswith("SELECT receipt,typeof(receipt)"))
        for key, proof, message in (
                ("missing", self.proof, "historical receipt not found"),
                ("missing", "0" * 64, "expected proof mismatch"),
                ("demo-1", "0" * 64, "expected proof mismatch")):
            with self.assertRaisesRegex(ValueError, message):
                store.lookup_receipt(key, expected_proof=proof)
            self.assertFalse(store.db.in_transaction)
        self.assertEqual(store.db.total_changes, changes)
        self.assertTrue(all(sql.split()[0] in ("BEGIN", "SELECT", "COMMIT", "ROLLBACK")
                            for sql in trace), trace)
        self.assertNotIn("BEGIN IMMEDIATE", trace)
        self.assertEqual(before, self.snapshot())

    def test_malformed_arguments_reject_before_any_database_operation(self):
        class Text(str):
            pass

        store = self.reader()
        database = store.db
        store.db = Mock()
        try:
            bad_keys = (None, True, 1, b"demo-1", [], {}, Text("demo-1"), "",
                        "a" * 49, "DEMO", "with space", "é", "a\x00", "a\n", "a_")
            bad_proofs = (fixture._UNSET, None, True, 1, b"a" * 64, [], {},
                          Text(self.proof), "", "a" * 63, "a" * 65, "A" * 64,
                          "g" * 64, "é" * 64, self.proof + "\n", "\x00" * 64)
            for key in bad_keys:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    store.lookup_receipt(key, expected_proof=self.proof)
            for proof in bad_proofs:
                with self.subTest(proof=proof), self.assertRaises(ValueError):
                    store.lookup_receipt("demo-1", expected_proof=proof)
            with self.assertRaises(TypeError):
                store.lookup_receipt("demo-1")
            with self.assertRaises(TypeError):
                store.lookup_receipt("demo-1", self.proof)
            self.assertEqual(store.db.mock_calls, [])
        finally:
            store.db = database

    def test_writable_store_guard_runs_first(self):
        store = fixture.Store(self.path, SOURCE)
        store.close()
        with self.assertRaisesRegex(ValueError, "requires a read-only store"):
            store.lookup_receipt(None, expected_proof=fixture._UNSET)

    def test_key_boundaries_and_parameterized_lookup(self):
        writer = fixture.Store(self.path, SOURCE)
        expected = {}
        for key in ("a", "-", "0", "a" * 48):
            expected[key] = writer.submit(fixture.request(key))
        envelope = writer.export()
        writer.close()
        store = self.reader()
        for key, receipt in expected.items():
            self.assertTrue(fixture.same(store.lookup_receipt(
                key, expected_proof=envelope["proof"]["digest"]), receipt))
        with self.assertRaises(ValueError):
            store.lookup_receipt("' OR 1=1 --", expected_proof=envelope["proof"]["digest"])

    def test_stale_proof_after_append_and_revocation_no_output(self):
        store = self.reader()
        writer = fixture.Store(self.path, SOURCE)
        for mutate in (lambda: writer.submit(fixture.request("later")), writer.revoke):
            mutate()
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, "expected proof mismatch"):
                store.lookup_receipt("demo-1", expected_proof=self.proof)
            self.rejected(self.cli("--receipt-output", str(self.output), proof=self.proof),
                          "expected proof mismatch")
            self.assertFalse(self.output.exists())
            self.assertEqual(before, self.snapshot())
            self.proof = writer.export()["proof"]["digest"]
        writer.close()

    def test_full_state_corruption_after_open_rejected_without_repair(self):
        pristine = self.path.read_bytes()
        mutations = (
            ("UPDATE requests SET receipt=? WHERE key='demo-1'", ('{}',)),
            ("UPDATE requests SET key=?", ("demo-1\x00",)),
            ("DELETE FROM requests", ()),
            ("DELETE FROM records WHERE seq=1", ()),
            ("DELETE FROM metadata", ()),
            ("INSERT INTO requests VALUES (?,?,?)", ("unrelated", "0" * 64, "{}")),
        )
        for sql, values in mutations:
            with self.subTest(sql=sql):
                self.path.write_bytes(pristine)
                store = self.reader()
                with sqlite3.connect(self.path) as other:
                    other.execute(sql, values)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    store.lookup_receipt("demo-1", expected_proof=self.proof)
                self.assertFalse(store.db.in_transaction)
                self.assertEqual(before, self.snapshot())
                self.rejected(self.cli("--receipt-output", str(self.output), proof=self.proof))
                self.assertFalse(self.output.exists())
                self.assertEqual(before, self.snapshot())
                store.close()

    def test_source_binding_rejects_without_output(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "source binding"):
            fixture.Store(self.path, "b" * 40, read_only=True)
        self.rejected(self.cli("--source-commit", "b" * 40,
                               "--receipt-output", str(self.output), proof=self.proof))
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.snapshot())

    def test_cli_stdout_only_exact_result(self):
        before = self.snapshot()
        result = self.cli(proof=self.proof)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertTrue(fixture.same(json.loads(result.stdout), {
            "result": "SYNTHETIC_HISTORICAL_RECEIPT", "request_key": "demo-1",
            "source_commit": SOURCE, "proof": self.proof, "receipt": self.receipt,
            "execution": False, "authenticity": False}))
        self.assertEqual(list(self.work.iterdir()), [self.path])
        self.assertEqual(before, self.snapshot())

    def test_cli_private_receipt_then_independent_revoked_review(self):
        writer = fixture.Store(self.path, SOURCE)
        writer.revoke()
        envelope = writer.export()
        writer.close()
        proof = envelope["proof"]["digest"]
        envelope_path = self.work / "envelope.json"
        fixture.publish_envelope(envelope_path, envelope)
        before = self.snapshot()
        result = self.cli("--receipt-output", str(self.output), proof=proof)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["proof"], proof)
        self.assertEqual(self.output.read_bytes(), fixture.canonical(self.receipt) + b"\n")
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        checked = subprocess.run([
            sys.executable, "-I", str(HERE / "verify.py"), str(envelope_path),
            "--receipt", str(self.output), "--expected-source-commit", SOURCE,
            "--expected-proof", proof, "--review-summary"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        result = json.loads(checked.stdout)
        self.assertEqual(result["receipt_verification"]["result"], "VERIFIED_HISTORICAL_RECEIPT")
        self.assertIs(result["receipt_verification"]["historical_record_only"], True)
        self.assertIs(result["receipt_verification"]["execution"], False)
        self.assertEqual(result["review_summary"]["revocation_sequence"], 6)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.work.glob(".era-envelope-*")))

    def test_cli_missing_database_never_created(self):
        missing = self.work / "missing.sqlite"
        self.rejected(self.cli("--receipt-output", str(self.output),
                               db=missing, proof=self.proof))
        self.assertFalse(missing.exists())
        self.assertFalse(self.output.exists())

    def test_cli_flags_and_syntax_reject_before_store_creation(self):
        cases = [
            ["receipt", "--expected-proof", self.proof],
            ["receipt", "--request-key", "demo-1"],
            ["receipt", "--request-key", "BAD", "--expected-proof", self.proof],
            ["receipt", "--request-key", "demo-1", "--expected-proof", "A" * 64],
            ["receipt", "--request-key", "demo-1", "--expected-proof", ""],
        ]
        for option in ("--envelope", "--backup-db"):
            cases.append(["receipt", "--request-key", "demo-1",
                          "--expected-proof", self.proof, option, str(self.output)])
        for command in ("demo", "export", "backup"):
            for flag, value in (("--request-key", "demo-1"),
                                ("--receipt-output", str(self.output))):
                cases.append([command, "--envelope", str(self.output), flag, value])
        missing = self.work / "missing.sqlite"
        for args in cases:
            with self.subTest(args=args), patch.object(fixture, "Store") as constructor:
                with patch.object(sys, "argv", ["fixture.py", *args, "--db", str(missing),
                                               "--source-commit", SOURCE]):
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                            SystemExit) as raised:
                        fixture.main()
                self.assertEqual(raised.exception.code, 2)
                constructor.assert_not_called()
                self.assertFalse(missing.exists())
                self.assertFalse(self.output.exists())

    def test_cli_missing_and_wrong_proof_fail_without_output(self):
        before = self.snapshot()
        for key, proof, message in (
                ("missing", self.proof, "historical receipt not found"),
                ("missing", "0" * 64, "expected proof mismatch"),
                ("demo-1", "0" * 64, "expected proof mismatch")):
            self.rejected(self.cli("--receipt-output", str(self.output),
                                   key=key, proof=proof), message)
            self.assertFalse(self.output.exists())
            self.assertEqual(before, self.snapshot())

    def test_existing_dangling_symlink_and_database_aliases_never_overwritten(self):
        existing = self.work / "existing.json"
        existing.write_bytes(b"retain")
        dangling = self.work / "dangling.json"
        dangling.symlink_to(self.work / "absent.json")
        hardlink = self.work / "hard.sqlite"
        hardlink.hardlink_to(self.path)
        symlink = self.work / "sym.sqlite"
        symlink.symlink_to(self.path)
        for path in (existing, dangling, self.path, hardlink, symlink):
            for proof in (self.proof, "0" * 64):
                before = self.snapshot()
                self.rejected(self.cli("--receipt-output", str(path), proof=proof))
                self.assertEqual(before, self.snapshot())
                self.assertEqual(existing.read_bytes(), b"retain")
                self.assertTrue(dangling.is_symlink())
                self.assertFalse(list(self.work.glob(".era-envelope-*")))

    def test_publication_failure_has_no_success_stdout_and_cleans_stage(self):
        before = self.snapshot()
        args = ["fixture.py", "receipt", "--db", str(self.path), "--source-commit", SOURCE,
                "--request-key", "demo-1", "--expected-proof", self.proof,
                "--receipt-output", str(self.output)]
        for operation in ("link", "fsync"):
            stdout = io.StringIO()
            with patch.object(sys, "argv", args), contextlib.redirect_stdout(stdout):
                with patch.object(fixture.os, operation, side_effect=OSError("publication failed")):
                    with self.assertRaisesRegex(OSError, "publication failed"):
                        fixture.main()
            self.assertEqual(stdout.getvalue(), "")
            self.assertFalse(self.output.exists())
            self.assertFalse(list(self.work.glob(".era-envelope-*")))
            self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
