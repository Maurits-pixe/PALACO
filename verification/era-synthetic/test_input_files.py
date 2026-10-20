"""Local regular-file input regressions; no runtime authority or release claims."""
import errno
import json
import os
from pathlib import Path
import socket
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


class InputFiles(unittest.TestCase):
    def setUp(self):
        runtime = HERE / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        store = fixture.Store(self.work / "state.sqlite", SOURCE)
        try:
            receipt = store.submit(fixture.request())
            self.previous = store.export()
            self.previous_proof = self.previous["proof"]["digest"]
            store.revoke()
            current = store.export()
        finally:
            store.close()
        self.proof = current["proof"]["digest"]
        self.current_path = self.work / "current.json"
        self.previous_path = self.work / "previous.json"
        self.receipt_path = self.work / "receipt.json"
        for path, value in ((self.current_path, current),
                            (self.previous_path, self.previous),
                            (self.receipt_path, receipt)):
            path.write_bytes(fixture.canonical(value))
        self.before = self.snapshot()

    def snapshot(self):
        return {path: path.read_bytes() for path in
                (self.current_path, self.previous_path, self.receipt_path)}

    def cli(self, path, role="current", *, accepted=False):
        current = path if role == "current" else self.current_path
        args = [sys.executable, "-I", str(HERE / "verify.py"), str(current),
                "--expected-source-commit", SOURCE, "--expected-proof", self.proof]
        if role == "previous":
            args += ["--previous-envelope", str(path),
                     "--expected-previous-proof", self.previous_proof]
        elif role == "receipt":
            args += ["--receipt", str(path)]
        started = time.monotonic()
        result = subprocess.run(args, capture_output=True, text=True, timeout=5)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result.returncode, 0 if accepted else 1,
                         result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        if accepted:
            self.assertEqual(output["result"], "VERIFIED_SYNTHETIC_ONLY")
            self.assertFalse(output["execution"])
            self.assertFalse(output["authenticity"])
        else:
            self.assertEqual(output, {"result": "REJECTED"})
        self.assertEqual(self.snapshot(), self.before)

    def reject_all_roles(self, path):
        for role in ("current", "previous", "receipt"):
            with self.subTest(role=role):
                self.cli(path, role)

    def test_fifo_without_writer_rejected_in_all_cli_modes(self):
        path = self.work / "pipe"
        os.mkfifo(path)
        self.reject_all_roles(path)

    def test_directory_rejected_in_all_cli_modes(self):
        self.reject_all_roles(self.work)

    def test_character_device_rejected_in_all_cli_modes(self):
        self.reject_all_roles(Path("/dev/null"))

    def test_unix_socket_rejected_in_all_cli_modes(self):
        path = self.work / "socket"
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(path))
            self.reject_all_roles(path)

    def test_symlink_to_fifo_rejected_in_all_cli_modes(self):
        path = self.work / "pipe"
        os.mkfifo(path)
        link = self.work / "link"
        link.symlink_to(path)
        self.reject_all_roles(link)

    def test_symlink_to_device_rejected(self):
        link = self.work / "link"
        link.symlink_to("/dev/null")
        self.reject_all_roles(link)

    def test_symlinks_to_regular_files_remain_compatible(self):
        for role, target in (("current", self.current_path),
                             ("previous", self.previous_path),
                             ("receipt", self.receipt_path)):
            with self.subTest(role=role):
                link = self.work / (role + ".link")
                link.symlink_to(target)
                self.cli(link, role, accepted=True)

    def test_readonly_regular_inputs_unchanged(self):
        for path in self.before:
            path.chmod(0o444)
            self.addCleanup(path.chmod, 0o644)
        self.cli(self.current_path, accepted=True)
        self.cli(self.previous_path, "previous", accepted=True)
        self.cli(self.receipt_path, "receipt", accepted=True)

    def test_stat_oversize_rejected_before_read(self):
        path = self.work / "oversize"
        for limit in (verify.LIMIT, 4096):
            with self.subTest(limit=limit):
                path.write_bytes(b"null" + b" " * (limit - 3))
                before = path.read_bytes()
                with patch.object(verify.os, "fdopen") as opened:
                    with self.assertRaises(ValueError):
                        verify._load_envelope(path, limit=limit)
                    opened.assert_not_called()
                self.assertEqual(path.read_bytes(), before)

    def test_exact_byte_limits_accepted(self):
        path = self.work / "boundary"
        for limit in (verify.LIMIT, 4096):
            with self.subTest(limit=limit):
                raw = b"null" + b" " * (limit - 4)
                path.write_bytes(raw)
                self.assertIsNone(verify._load_envelope(path, limit=limit))
                self.assertEqual(path.read_bytes(), raw)

    def test_growth_after_stat_cannot_bypass_actual_byte_limit(self):
        path = self.work / "growing"
        original = os.fstat
        for limit in (verify.LIMIT, 4096):
            with self.subTest(limit=limit):
                path.write_bytes(b"null")

                def grow(fd):
                    metadata = original(fd)
                    with path.open("ab") as stream:
                        stream.write(b" " * (limit - 3))
                    return metadata

                with patch.object(verify.os, "fstat", side_effect=grow):
                    with self.assertRaises(ValueError):
                        verify._load_envelope(path, limit=limit)
                self.assertEqual(path.stat().st_size, limit + 1)

    def test_single_readonly_path_open_and_same_descriptor(self):
        original_open, original_stat, original_fdopen = os.open, os.fstat, os.fdopen
        with patch.object(verify.os, "open", wraps=original_open) as opened, \
                patch.object(verify.os, "fstat", wraps=original_stat) as metadata, \
                patch.object(verify.os, "fdopen", wraps=original_fdopen) as stream:
            self.assertEqual(verify._load_envelope(self.previous_path), self.previous)
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        opened.assert_called_once_with(self.previous_path, flags)
        metadata.assert_called_once()
        fd = metadata.call_args.args[0]
        stream.assert_called_once_with(fd, "rb", closefd=False)
        self.assert_closed(fd)
        self.assertEqual(self.snapshot(), self.before)

    def test_path_replacement_after_open_still_reads_original_descriptor(self):
        path = self.work / "replaceable"
        path.write_bytes(b'{"original":true}')
        original = os.open

        def replace(target, flags):
            fd = original(target, flags)
            path.rename(self.work / "original")
            path.write_bytes(b"not JSON")
            return fd

        with patch.object(verify.os, "open", side_effect=replace) as opened:
            self.assertEqual(verify._load_envelope(path), {"original": True})
        self.assertEqual(opened.call_count, 1)

    def assert_closed(self, fd):
        with self.assertRaises(OSError) as caught:
            os.fstat(fd)
        self.assertEqual(caught.exception.errno, errno.EBADF)

    def check_cleanup(self, *, failure=None, raw=b"null"):
        path = self.work / "cleanup"
        path.write_bytes(raw)
        descriptors = []
        original = os.open

        def capture(target, flags):
            fd = original(target, flags)
            descriptors.append(fd)
            return fd

        with patch.object(verify.os, "open", side_effect=capture):
            if failure == "fstat":
                with patch.object(verify.os, "fstat", side_effect=OSError("stat failed")):
                    with self.assertRaises(OSError):
                        verify._load_envelope(path)
            elif failure == "fdopen":
                with patch.object(verify.os, "fdopen", side_effect=OSError("open failed")):
                    with self.assertRaises(OSError):
                        verify._load_envelope(path)
            elif failure == "read":
                stream = MagicMock()
                stream.__enter__.return_value.read.side_effect = OSError("read failed")
                with patch.object(verify.os, "fdopen", return_value=stream):
                    with self.assertRaises(OSError):
                        verify._load_envelope(path)
            elif failure == "parse":
                with self.assertRaises(ValueError):
                    verify._load_envelope(path)
            else:
                self.assertIsNone(verify._load_envelope(path))
        self.assertEqual(len(descriptors), 1)
        self.assert_closed(descriptors[0])
        self.assertEqual(path.read_bytes(), raw)

    def test_descriptor_closed_after_fstat_failure(self):
        self.check_cleanup(failure="fstat")

    def test_descriptor_closed_after_fdopen_failure(self):
        self.check_cleanup(failure="fdopen")

    def test_descriptor_closed_after_read_failure(self):
        self.check_cleanup(failure="read")

    def test_descriptor_closed_after_json_parse_failure(self):
        self.check_cleanup(failure="parse", raw=b"{")

    def test_descriptor_closed_after_success(self):
        self.check_cleanup()

    def test_descriptor_closed_after_nonregular_rejection(self):
        path = self.work / "pipe"
        os.mkfifo(path)
        original = os.open
        descriptors = []

        def capture(target, flags):
            fd = original(target, flags)
            descriptors.append(fd)
            return fd

        with patch.object(verify.os, "open", side_effect=capture):
            with self.assertRaises(ValueError):
                verify._load_envelope(path)
        self.assertEqual(len(descriptors), 1)
        self.assert_closed(descriptors[0])

    def test_invalid_anchors_and_preconditions_reject_before_os_open(self):
        options = [
            {"review_summary": True},
            {"receipt": self.receipt_path},
            {"previous_envelope": self.previous_path},
            {"expected_previous_proof": self.previous_proof},
        ]
        for bad in (None, "", "A" * 64, 42):
            options += [
                {"expected_source_commit": bad},
                {"expected_proof": bad},
                {"previous_envelope": self.previous_path, "expected_previous_proof": bad},
            ]
        for kwargs in options:
            with self.subTest(options=kwargs), patch.object(verify.os, "open") as opened:
                with self.assertRaises(ValueError):
                    verify.verify(self.current_path, **kwargs)
                opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
