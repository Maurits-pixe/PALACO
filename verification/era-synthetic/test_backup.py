"""Controlled SQLite backup/reopen regressions; never restore or real authority."""
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import fixture
import verify

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40


class VerifiedBackup(unittest.TestCase):
    def setUp(self):
        work = HERE / ".runtime"
        work.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.db = self.path / "source.sqlite"
        self.output = self.path / "backup.sqlite"
        store = self.open_store()
        self.receipt = store.submit(fixture.request())
        self.envelope = store.export()
        store.close()
        self.proof = self.envelope["proof"]["digest"]
        self.reader = self.open_store(read_only=True)
        self.original = self.snapshot()

    def open_store(self, path=None, *, read_only=False):
        store = fixture.Store(path or self.db, SOURCE, read_only=read_only)
        self.addCleanup(store.close)
        return store

    def snapshot(self):
        return self.db.read_bytes(), self.db.stat().st_mtime_ns

    def backup(self, **kwargs):
        return self.reader.backup(self.output, expected_proof=self.proof, **kwargs)

    def assert_clean(self, *, final=False):
        self.assertEqual(list(self.path.glob(".era-backup-*")), [])
        self.assertEqual(self.output.exists(), final)
        self.assertEqual(self.snapshot(), self.original)
        self.assertFalse(self.reader.db.in_transaction)
        self.assertEqual(self.reader.db.execute("SELECT 1").fetchone(), (1,))

    def assert_complete(self):
        self.assertTrue(self.output.read_bytes().startswith(b"SQLite format 3\x00"))
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        reopened = self.open_store(self.output, read_only=True)
        self.assertEqual(reopened.export(expected_proof=self.proof), self.envelope)
        reopened.close()

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-I", str(HERE / "fixture.py"), *args],
            capture_output=True, text=True, timeout=10)

    def test_sqlite_reopen_export_and_independent_checker(self):
        result = self.backup()
        self.assertEqual(result, {
            "result": "SYNTHETIC_BACKUP_VERIFIED", "records": 5, "proof": self.proof,
            "source_commit": SOURCE, "execution": False, "authenticity": False})
        self.assert_complete()
        reopened = self.open_store(self.output, read_only=True)
        envelope = reopened.export(expected_proof=self.proof)
        export_path = self.path / "backup-envelope.json"
        fixture.publish_envelope(export_path, envelope)
        checked = verify.verify(export_path, expected_source_commit=SOURCE,
                                expected_proof=self.proof)
        self.assertEqual(checked["result"], "VERIFIED_SYNTHETIC_ONLY")
        self.assertIs(checked["execution"], False)
        independent = subprocess.run(
            [sys.executable, "-I", str(HERE / "verify.py"), str(export_path),
             "--expected-source-commit", SOURCE, "--expected-proof", self.proof],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(independent.returncode, 0, independent.stderr)
        self.assertEqual(json.loads(independent.stdout)["proof"], self.proof)
        self.assert_clean(final=True)

    def test_explicit_writable_copy_accepts_fresh_fixed_request_only_in_copy(self):
        self.backup()
        copy = self.open_store(self.output)
        self.assertIs(copy.submit(fixture.request("copy-only"))["execution"], False)
        self.assertEqual(len(copy.export()["records"]), 10)
        self.assertEqual(self.reader.export(), self.envelope)
        self.assert_clean(final=True)

    def test_revocation_and_historical_retry_survive_explicit_writable_reopen(self):
        writer = self.open_store()
        writer.revoke()
        self.envelope = writer.export()
        writer.close()
        self.proof = self.envelope["proof"]["digest"]
        self.original = self.snapshot()
        self.backup()
        copy = self.open_store(self.output)
        before = self.output.read_bytes(), self.output.stat().st_mtime_ns
        self.assertEqual(copy.submit(fixture.request()), self.receipt)
        with self.assertRaisesRegex(ValueError, "revoked"):
            copy.submit(fixture.request("new"))
        self.assertEqual((self.output.read_bytes(), self.output.stat().st_mtime_ns), before)
        self.assert_complete()
        self.assert_clean(final=True)

    def test_anchor_is_required_keyword_only_and_strict_before_staging(self):
        with patch.object(fixture.tempfile, "mkstemp") as stage:
            with self.assertRaises(TypeError):
                self.reader.backup(self.output)
            with self.assertRaises(TypeError):
                self.reader.backup(self.output, self.proof)
            for proof in (None, 1, True, b"a" * 64, "", "A" * 64, "a" * 63,
                          "a" * 65, "g" * 64, [], {}):
                with self.subTest(proof=proof), self.assertRaises(ValueError):
                    self.reader.backup(self.output, expected_proof=proof)
            stage.assert_not_called()
        self.assert_clean()

    def test_writable_store_rejected_before_staging(self):
        writer = self.open_store()
        with patch.object(fixture.tempfile, "mkstemp") as stage:
            with self.assertRaisesRegex(ValueError, "read-only"):
                writer.backup(self.output, expected_proof=self.proof)
            stage.assert_not_called()
        self.assert_clean()

    def test_wrong_anchor_cleans_stage_and_preserves_source(self):
        with self.assertRaisesRegex(ValueError, "proof mismatch"):
            self.reader.backup(self.output, expected_proof="0" * 64)
        self.assert_clean()

    def test_changed_snapshot_rejects_old_proof_but_accepts_updated_caller_anchor(self):
        writer = self.open_store()
        writer.submit(fixture.request("later"))
        self.envelope = writer.export()
        writer.close()
        self.original = self.snapshot()
        with self.assertRaisesRegex(ValueError, "proof mismatch"):
            self.backup()
        self.assert_clean()
        self.proof = self.envelope["proof"]["digest"]
        self.backup()
        self.assert_complete()
        self.assert_clean(final=True)

    def test_corrupted_source_after_open_is_not_published_or_repaired(self):
        changes = [
            ("DELETE FROM requests", ()),
            ("UPDATE metadata SET source=?", ('{"commit":"wrong"}',)),
            ("UPDATE records SET body='{}' WHERE seq=1", ()),
        ]
        for statement, values in changes:
            with self.subTest(statement=statement):
                before = self.db.read_bytes()
                with sqlite3.connect(self.db) as connection:
                    connection.execute(statement, values)
                self.original = self.snapshot()
                with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                    self.backup()
                self.assert_clean()
                self.db.write_bytes(before)
        self.original = self.snapshot()

    def test_readonly_connection_stays_write_denied(self):
        self.backup()
        for store in (self.reader, self.open_store(self.output, read_only=True)):
            with self.assertRaises(sqlite3.OperationalError):
                store.db.execute("DELETE FROM requests")
            with self.assertRaises(ValueError):
                store.submit(fixture.request())
            with self.assertRaises(ValueError):
                store.revoke()
        self.assert_clean(final=True)

    def test_active_source_transaction_rejected_immediately(self):
        self.reader.db.execute("BEGIN")
        try:
            with patch.object(fixture.tempfile, "mkstemp") as stage:
                with self.assertRaisesRegex(ValueError, "active source transaction"):
                    self.backup()
                stage.assert_not_called()
            self.assertTrue(self.reader.db.in_transaction)
        finally:
            self.reader.db.rollback()
        self.assert_clean()

    def test_existing_targets_and_source_aliases_never_clobbered(self):
        file = self.path / "retained.sqlite"
        file.write_bytes(b"caller-owned")
        dangling = self.path / "dangling"
        dangling.symlink_to("absent")
        directory = self.path / "directory"
        directory.mkdir()
        hardlink = self.path / "source-hardlink"
        os.link(self.db, hardlink)
        symlink = self.path / "source-symlink"
        symlink.symlink_to(self.db)
        for destination in (file, dangling, directory, self.db, hardlink, symlink):
            with self.subTest(destination=destination):
                before = destination.lstat()
                with self.assertRaises(FileExistsError):
                    self.reader.backup(destination, expected_proof=self.proof)
                self.assertEqual(destination.lstat(), before)
                self.assert_clean()
        self.assertEqual(file.read_bytes(), b"caller-owned")
        self.assertEqual(os.readlink(dangling), "absent")
        self.assertEqual(list(directory.iterdir()), [])
        self.assertFalse((self.path / "absent").exists())

    def test_closed_file_fsync_link_directory_fsync_cleanup_order(self):
        calls = []
        fsync, link, unlink = os.fsync, os.link, os.unlink

        def sync(descriptor):
            kind = "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
            calls.append(kind)
            if kind == "file":
                self.assertFalse(self.output.exists())
                stages = list(self.path.glob(".era-backup-*.sqlite"))
                self.assertEqual(len(stages), 1)
                self.assertTrue(stages[0].read_bytes().startswith(b"SQLite format 3\x00"))
                self.assertEqual(stat.S_IMODE(stages[0].stat().st_mode), 0o600)
            else:
                self.assert_complete()
            return fsync(descriptor)

        def publish(*args, **kwargs):
            calls.append("link")
            return link(*args, **kwargs)

        def cleanup(name, **kwargs):
            if name.endswith(".sqlite"):
                calls.append("unlink")
            return unlink(name, **kwargs)

        def checkpoint(stage):
            calls.append(stage)

        with patch.object(fixture.os, "fsync", side_effect=sync), \
                patch.object(fixture.os, "link", side_effect=publish), \
                patch.object(fixture.os, "unlink", side_effect=cleanup):
            self.backup(_checkpoint=checkpoint)
        self.assertEqual(calls, ["file", "before_publish", "link", "after_publish",
                                 "directory", "unlink"])
        self.assert_clean(final=True)

    def test_sqlite_backup_failure_closes_target_and_cleans_stage_sidecars(self):
        real = self.reader.db
        proxy = MagicMock(wraps=real)
        proxy.in_transaction = False
        target_seen = []

        def fail(target, **kwargs):
            target_seen.append(target)
            target.execute("CREATE TABLE partial (value)")
            target.execute("BEGIN IMMEDIATE")
            target.execute("INSERT INTO partial VALUES (1)")
            raise sqlite3.OperationalError("injected backup failure")

        proxy.backup.side_effect = fail
        with patch.object(self.reader, "db", proxy):
            with self.assertRaisesRegex(sqlite3.OperationalError, "injected backup"):
                self.backup()
        with self.assertRaises(sqlite3.ProgrammingError):
            target_seen[0].execute("SELECT 1")
        self.assert_clean()

    def test_independent_destination_validation_rejects_bad_snapshot(self):
        real = self.reader.db
        proxy = MagicMock(wraps=real)
        proxy.in_transaction = False

        def corrupt(target, **kwargs):
            real.backup(target, **kwargs)
            target.execute("DELETE FROM requests")

        proxy.backup.side_effect = corrupt
        with patch.object(self.reader, "db", proxy):
            with self.assertRaisesRegex(ValueError, "mapping mismatch"):
                self.backup()
        self.assert_clean()

    def test_physical_quick_check_failure_rejects_destination(self):
        real_connect = sqlite3.connect
        opened = []

        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            if str(args[0]).startswith("file:") and ".era-backup-" in str(args[0]):
                opened.append(connection)
                proxy = MagicMock(wraps=connection)

                def execute(sql, *values):
                    if sql == "PRAGMA quick_check":
                        result = MagicMock()
                        result.fetchall.return_value = [("injected physical corruption",)]
                        return result
                    return connection.execute(sql, *values)

                proxy.execute.side_effect = execute
                return proxy
            return connection

        with patch.object(fixture.sqlite3, "connect", side_effect=connect):
            with self.assertRaisesRegex(ValueError, "quick_check"):
                self.backup()
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")
        self.assert_clean()

    def test_file_fsync_and_link_failures_leave_no_final_or_stage(self):
        for operation in ("fsync", "link"):
            with self.subTest(operation=operation):
                with patch.object(fixture.os, operation, side_effect=OSError(operation)):
                    with self.assertRaisesRegex(OSError, operation):
                        self.backup()
                self.assert_clean()

    def test_stage_and_destination_connect_failures_leave_no_outputs(self):
        with patch.object(fixture.tempfile, "mkstemp", side_effect=OSError("stage")):
            with self.assertRaisesRegex(OSError, "stage"):
                self.backup()
        self.assert_clean()
        with patch.object(fixture.sqlite3, "connect", side_effect=sqlite3.Error("connect")):
            with self.assertRaisesRegex(sqlite3.Error, "connect"):
                self.backup()
        self.assert_clean()

    def test_directory_fsync_failure_keeps_complete_final_without_success(self):
        fsync = os.fsync

        def fail(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("directory sync")
            fsync(descriptor)

        with patch.object(fixture.os, "fsync", side_effect=fail):
            with self.assertRaisesRegex(OSError, "directory sync"):
                self.backup()
        self.assert_complete()
        self.assert_clean(final=True)
        with self.assertRaises(FileExistsError):
            self.backup()

    def test_callback_failure_before_or_after_link_preserves_boundary(self):
        for stage in ("before_publish", "after_publish"):
            with self.subTest(stage=stage):
                def fail(current):
                    if current == stage:
                        raise RuntimeError(stage)

                with self.assertRaisesRegex(RuntimeError, stage):
                    self.backup(_checkpoint=fail)
                self.assert_clean(final=stage == "after_publish")
                if stage == "after_publish":
                    self.assert_complete()

    def test_cleanup_failure_reports_error_but_never_deletes_final(self):
        unlink = os.unlink

        def fail(name, **kwargs):
            if name.endswith(".sqlite"):
                raise OSError("cleanup")
            return unlink(name, **kwargs)

        with patch.object(fixture.os, "unlink", side_effect=fail):
            with self.assertRaisesRegex(OSError, "cleanup"):
                self.backup()
        self.assert_complete()
        stages = list(self.path.glob(".era-backup-*"))
        self.assertEqual(len(stages), 1)
        stages[0].unlink()
        self.assert_clean(final=True)

    def test_exclusive_source_lock_is_bounded_by_progress_timeout(self):
        locked = sqlite3.connect(self.db, isolation_level=None)
        locked.execute("BEGIN EXCLUSIVE")
        start = time.monotonic()
        try:
            with self.assertRaisesRegex(TimeoutError, "two-second"):
                self.backup()
        finally:
            locked.rollback()
            locked.close()
        self.assertLess(time.monotonic() - start, 5)
        self.assert_clean()

    def test_empty_and_revoked_only_valid_internal_backups(self):
        for revoked in (False, True):
            with self.subTest(revoked=revoked):
                source = self.path / f"empty-{revoked}.sqlite"
                destination = self.path / f"empty-copy-{revoked}.sqlite"
                store = self.open_store(source)
                if revoked:
                    store.revoke()
                envelope = store.export()
                store.close()
                reader = self.open_store(source, read_only=True)
                result = reader.backup(destination, expected_proof=envelope["proof"]["digest"])
                self.assertEqual(result["records"], int(revoked))
                copy = self.open_store(destination, read_only=True)
                self.assertEqual(copy.export(), envelope)
                export_path = self.path / f"empty-{revoked}.json"
                fixture.publish_envelope(export_path, envelope)
                with self.assertRaises(ValueError):
                    verify.verify(export_path)
        self.assert_clean()

    def test_cli_backup_success_and_readonly_export(self):
        result = self.cli("backup", "--db", str(self.db), "--backup-db", str(self.output),
                          "--source-commit", SOURCE, "--expected-proof", self.proof)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(result.stdout)), {
            "result", "records", "proof", "source_commit", "execution", "authenticity"})
        self.assertEqual(json.loads(result.stdout)["result"], "SYNTHETIC_BACKUP_VERIFIED")
        export_path = self.path / "cli-export.json"
        result = self.cli("export", "--db", str(self.output), "--envelope", str(export_path),
                          "--source-commit", SOURCE, "--expected-proof", self.proof)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(verify.verify(export_path, expected_proof=self.proof)["records"], 5)
        self.assert_complete()
        self.assert_clean(final=True)

    def test_cli_invalid_flag_combinations_do_not_create_source_or_outputs(self):
        missing = self.path / "missing.sqlite"
        base = ["--db", str(missing), "--source-commit", SOURCE]
        output = ["--backup-db", str(self.output)]
        proof = ["--expected-proof", self.proof]
        envelope = ["--envelope", str(self.path / "export.json")]
        cases = [
            ["backup", *base, *output],
            ["backup", *base, *proof],
            ["backup", *base, *output, *proof, *envelope],
            ["backup", *base, *output, "--expected-proof", "A" * 64],
            ["demo", *base, *output, *envelope],
            ["export", *base, *output, *envelope],
            ["demo", *base, *envelope, *proof],
            ["demo", *base],
            ["export", *base],
            ["backup", *output, *proof, "--source-commit", SOURCE],
            ["backup", "--db", str(missing), *output, *proof],
        ]
        before = set(self.path.iterdir())
        for args in cases:
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(set(self.path.iterdir()), before)
        self.assert_clean()

    def test_missing_source_wrong_binding_and_proof_cli_fail_without_output(self):
        for source, commit, proof in (
                (self.path / "missing.sqlite", SOURCE, self.proof),
                (self.db, "b" * 40, self.proof),
                (self.db, SOURCE, "0" * 64)):
            with self.subTest(source=source, commit=commit, proof=proof):
                result = self.cli("backup", "--db", str(source),
                                  "--backup-db", str(self.output),
                                  "--source-commit", commit, "--expected-proof", proof)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assert_clean()
                self.assertFalse((self.path / "missing.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
