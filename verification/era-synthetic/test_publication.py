"""Exclusive publication and process-interruption regressions, not power-loss tests."""
import contextlib
import errno
import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import fixture
import verify

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40


def publisher(db, output, connection, pause):
    """Child-owned paths and explicit IPC keep scheduling independent of sleeps."""
    try:
        store = fixture.Store(db, SOURCE, read_only=True)
        try:
            envelope = store.export()
        finally:
            store.close()

        def checkpoint(stage):
            if stage == pause:
                connection.send((stage, [
                    str(path) for path in output.parent.glob(".era-envelope-*.tmp")]))
                connection.recv()

        fixture.publish_envelope(output, envelope, _checkpoint=checkpoint)
        connection.send(("success", None))
    except FileExistsError:
        connection.send(("exists", None))
    except BaseException as error:
        connection.send(("error", repr(error)))
    finally:
        connection.close()


class EnvelopePublication(unittest.TestCase):
    def setUp(self):
        work = HERE / ".runtime"
        work.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.db = self.path / "state.sqlite"
        self.output = self.path / "envelope.json"
        store = fixture.Store(self.db, SOURCE)
        try:
            store.submit(fixture.request())
            store.revoke()
            self.envelope = store.export()
        finally:
            store.close()
        self.payload = fixture.canonical(self.envelope) + b"\n"

    def stages(self):
        return list(self.path.glob(".era-envelope-*.tmp"))

    def assert_complete(self):
        self.assertEqual(self.output.read_bytes(), self.payload)
        result = verify.verify(
            self.output, expected_source_commit=SOURCE,
            expected_proof=self.envelope["proof"]["digest"])
        self.assertIs(result["execution"], False)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)

    def start_child(self, pause):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=publisher, args=(self.db, self.output, child, pause))
        process.start()
        child.close()

        def cleanup():
            if process.is_alive():
                process.kill()
            process.join(10)
            parent.close()
            process.close()

        self.addCleanup(cleanup)
        return process, parent

    def receive(self, connection):
        self.assertTrue(connection.poll(10), "publisher IPC timed out")
        return connection.recv()

    def test_complete_private_envelope_and_sync_link_order(self):
        calls = []
        fsync, link, unlink = os.fsync, os.link, os.unlink

        def sync(descriptor):
            kind = "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
            calls.append(kind)
            if kind == "file":
                self.assertFalse(self.output.exists())
                self.assertEqual(self.stages()[0].read_bytes(), self.payload)
                self.assertEqual(stat.S_IMODE(self.stages()[0].stat().st_mode), 0o600)
            else:
                self.assert_complete()
            fsync(descriptor)

        def publish(*args, **kwargs):
            calls.append("link")
            return link(*args, **kwargs)

        def cleanup(*args, **kwargs):
            calls.append("unlink")
            return unlink(*args, **kwargs)

        with patch.object(fixture.os, "fsync", side_effect=sync), \
                patch.object(fixture.os, "link", side_effect=publish), \
                patch.object(fixture.os, "unlink", side_effect=cleanup):
            fixture.publish_envelope(self.output, self.envelope)
        self.assertEqual(calls, ["file", "link", "directory", "unlink"])
        self.assert_complete()
        self.assertEqual(self.stages(), [])

    def test_existing_file_dangling_symlink_and_directory_are_unchanged(self):
        targets = [self.path / name for name in ("file", "symlink", "directory")]
        targets[0].write_bytes(b"caller-owned bytes")
        targets[1].symlink_to("absent-target")
        targets[2].mkdir()
        for target in targets:
            with self.subTest(target=target):
                before = target.lstat()
                with self.assertRaises(FileExistsError):
                    fixture.publish_envelope(target, self.envelope)
                self.assertEqual(target.lstat(), before)
                self.assertEqual(self.stages(), [])
        self.assertEqual(targets[0].read_bytes(), b"caller-owned bytes")
        self.assertEqual(os.readlink(targets[1]), "absent-target")
        self.assertEqual(list(targets[2].iterdir()), [])
        self.assertFalse((self.path / "absent-target").exists())

    def test_serialization_failure_creates_nothing(self):
        before = set(self.path.iterdir())
        for invalid in ({"value": object()}, {"value": float("nan")}):
            with self.subTest(invalid=invalid):
                with patch.object(fixture.tempfile, "mkstemp") as create:
                    with self.assertRaises((TypeError, ValueError)):
                        fixture.publish_envelope(self.output, invalid)
                    create.assert_not_called()
                self.assertEqual(set(self.path.iterdir()), before)

    def test_write_short_write_and_flush_errors_leave_no_final_or_stage(self):
        fdopen = os.fdopen
        for operation in ("write", "short-write", "flush"):
            with self.subTest(operation=operation):
                def failing_stream(*args, **kwargs):
                    stream = fdopen(*args, **kwargs)
                    wrapper = MagicMock(wraps=stream)
                    wrapper.__enter__.return_value = wrapper
                    wrapper.__exit__.side_effect = stream.__exit__
                    if operation == "short-write":
                        wrapper.write.return_value = len(self.payload) - 1
                    else:
                        getattr(wrapper, operation).side_effect = OSError(operation)
                    return wrapper

                with patch.object(fixture.os, "fdopen", side_effect=failing_stream), \
                        patch.object(fixture.os, "link") as link:
                    with self.assertRaises(OSError):
                        fixture.publish_envelope(self.output, self.envelope)
                    link.assert_not_called()
                self.assertFalse(self.output.exists())
                self.assertEqual(self.stages(), [])

    def test_file_sync_failure_prevents_publication(self):
        with patch.object(fixture.os, "fsync", side_effect=OSError("file sync")), \
                patch.object(fixture.os, "link") as link:
            with self.assertRaisesRegex(OSError, "file sync"):
                fixture.publish_envelope(self.output, self.envelope)
            link.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.stages(), [])

    def test_unsupported_hardlinks_fail_without_fallback_or_collateral_changes(self):
        existing = self.path / "retained.json"
        existing.write_bytes(b"retained")
        for target in (self.output, existing):
            with self.subTest(target=target):
                with patch.object(fixture.os, "link",
                                  side_effect=OSError(errno.EOPNOTSUPP, "unsupported")):
                    with self.assertRaises(OSError) as raised:
                        fixture.publish_envelope(target, self.envelope)
                    self.assertEqual(raised.exception.errno, errno.EOPNOTSUPP)
                self.assertFalse(self.output.exists())
                self.assertEqual(existing.read_bytes(), b"retained")
                self.assertEqual(self.stages(), [])

    def test_directory_sync_error_keeps_complete_final_and_propagates(self):
        fsync = os.fsync

        def sync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("directory sync")
            fsync(descriptor)

        with patch.object(fixture.os, "fsync", side_effect=sync):
            with self.assertRaisesRegex(OSError, "directory sync"):
                fixture.publish_envelope(self.output, self.envelope)
        self.assert_complete()
        self.assertEqual(self.stages(), [])
        with self.assertRaises(FileExistsError):
            fixture.publish_envelope(self.output, self.envelope)
        self.assert_complete()

    def test_checkpoint_exceptions_cleanup_without_deleting_published_final(self):
        for stop in ("before_publish", "after_publish"):
            with self.subTest(stop=stop):
                observed = []

                def checkpoint(stage):
                    observed.append(stage)
                    if stage == stop:
                        raise RuntimeError(stage)

                with self.assertRaisesRegex(RuntimeError, stop):
                    fixture.publish_envelope(
                        self.output, self.envelope, _checkpoint=checkpoint)
                self.assertEqual(self.stages(), [])
                if stop == "before_publish":
                    self.assertEqual(observed, ["before_publish"])
                    self.assertFalse(self.output.exists())
                else:
                    self.assertEqual(observed, ["before_publish", "after_publish"])
                    self.assert_complete()

    def test_cleanup_error_after_link_is_not_reported_as_success(self):
        with patch.object(fixture.os, "unlink", side_effect=OSError("stage cleanup")):
            with self.assertRaisesRegex(OSError, "stage cleanup"):
                fixture.publish_envelope(self.output, self.envelope)
        self.assert_complete()
        self.assertEqual(len(self.stages()), 1)
        self.stages()[0].unlink()

    def test_directory_sync_error_remains_in_cleanup_error_chain(self):
        fsync = os.fsync

        def sync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("directory sync")
            fsync(descriptor)

        with patch.object(fixture.os, "fsync", side_effect=sync), \
                patch.object(fixture.os, "unlink", side_effect=OSError("stage cleanup")):
            with self.assertRaisesRegex(OSError, "stage cleanup") as raised:
                fixture.publish_envelope(self.output, self.envelope)
        self.assertIn("directory sync", str(raised.exception.__context__))
        self.assert_complete()
        self.stages()[0].unlink()

    def test_two_process_publishers_have_exactly_one_winner(self):
        children = [self.start_child("before_publish") for _ in range(2)]
        for _, connection in children:
            self.assertEqual(self.receive(connection)[0], "before_publish")
        self.assertFalse(self.output.exists())
        for _, connection in children:
            connection.send("publish")
        results = [self.receive(connection)[0] for _, connection in children]
        for process, _ in children:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        self.assertCountEqual(results, ["success", "exists"])
        self.assert_complete()
        before = self.output.read_bytes(), self.output.stat()
        with self.assertRaises(FileExistsError):
            fixture.publish_envelope(self.output, self.envelope)
        self.assertEqual((self.output.read_bytes(), self.output.stat()), before)
        self.assertEqual(self.stages(), [])

    @unittest.skipUnless(hasattr(signal, "SIGKILL"), "requires SIGKILL")
    def test_sigkill_before_link_leaves_no_final_and_only_known_private_orphan(self):
        process, connection = self.start_child("before_publish")
        stage, names = self.receive(connection)
        self.assertEqual(stage, "before_publish")
        self.assertFalse(self.output.exists())
        self.assertEqual(len(names), 1)
        orphan = Path(names[0])
        self.assertEqual(orphan.parent, self.path)
        self.assertEqual(stat.S_IMODE(orphan.stat().st_mode), 0o600)
        os.kill(process.pid, signal.SIGKILL)
        process.join(10)
        self.assertEqual(process.exitcode, -signal.SIGKILL)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.stages(), [orphan])
        orphan.unlink()

    @unittest.skipUnless(hasattr(signal, "SIGKILL"), "requires SIGKILL")
    def test_sigkill_after_link_leaves_complete_verifiable_final(self):
        process, connection = self.start_child("after_publish")
        stage, names = self.receive(connection)
        self.assertEqual(stage, "after_publish")
        self.assertEqual(len(names), 1)
        self.assert_complete()
        os.kill(process.pid, signal.SIGKILL)
        process.join(10)
        self.assertEqual(process.exitcode, -signal.SIGKILL)
        self.assert_complete()
        orphan = Path(names[0])
        self.assertEqual(orphan.parent, self.path)
        self.assertEqual(self.stages(), [orphan])
        orphan.unlink()
        self.assert_complete()

    def test_readonly_export_cli_is_exclusive_and_does_not_modify_database(self):
        before = self.db.read_bytes(), self.db.stat().st_mtime_ns
        command = [
            sys.executable, "-I", str(HERE / "fixture.py"), "export",
            "--db", str(self.db), "--envelope", str(self.output),
            "--source-commit", SOURCE, "--expected-proof", self.envelope["proof"]["digest"]]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "result": "SYNTHETIC_READ_ONLY_EXPORT", "records": 6,
            "proof": self.envelope["proof"]["digest"], "execution": False,
            "authenticity": False, "source_commit": SOURCE})
        self.assert_complete()
        published = self.output.read_bytes(), self.output.stat()
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual((self.output.read_bytes(), self.output.stat()), published)
        self.assertEqual((self.db.read_bytes(), self.db.stat().st_mtime_ns), before)
        self.assertEqual(self.stages(), [])

    def test_cli_never_prints_success_on_postpublication_errors(self):
        fsync = os.fsync

        def sync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("directory sync")
            fsync(descriptor)

        for failure in ("fsync", "unlink"):
            with self.subTest(failure=failure):
                output = self.path / (failure + ".json")
                argv = ["fixture.py", "export", "--db", str(self.db),
                        "--envelope", str(output), "--source-commit", SOURCE]
                stdout = io.StringIO()
                effect = sync if failure == "fsync" else OSError("stage cleanup")
                with patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout), \
                        patch.object(fixture.os, failure, side_effect=effect):
                    with self.assertRaises(OSError):
                        fixture.main()
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(output.read_bytes(), self.payload)
                if failure == "unlink":
                    self.assertEqual(len(self.stages()), 1)
                    self.stages()[0].unlink()
                self.assertEqual(self.stages(), [])


if __name__ == "__main__":
    unittest.main()
