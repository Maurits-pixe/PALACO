"""Real-process lost-acknowledgement drills, not official WF or power-loss evidence."""
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import fixture

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# Test-only control: neither the request nor the fixture CLI exposes these barriers.
WORKER = """
import select, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import fixture
store = fixture.Store(sys.argv[2], sys.argv[3])
def control():
    if not select.select([sys.stdin], [], [], 30)[0]:
        raise RuntimeError("control timeout")
    if sys.stdin.readline() != "GO\\n":
        raise RuntimeError("unexpected control")
print("READY", flush=True)
control()
def checkpoint(stage):
    if stage == sys.argv[5]:
        print(stage, flush=True)
        control()
        raise RuntimeError("barrier must end with SIGKILL")
store.submit(fixture.request("second"), expected_proof=sys.argv[4],
             _checkpoint=checkpoint)
store.close()
raise RuntimeError("submission unexpectedly returned")
"""


@unittest.skipUnless(hasattr(signal, "SIGKILL"), "requires SIGKILL")
class ReceiptRecoveryDrill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True, timeout=10).stdout.strip()
        if len(cls.source_commit) != 40:
            raise AssertionError("runner must supply the actual 40-hex HEAD")

    def setUp(self):
        runtime = HERE / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.source = self.work / "source.sqlite"
        writer = fixture.Store(self.source, self.source_commit)
        try:
            self.first_receipt = writer.submit(
                fixture.request("first"), expected_proof=writer.export()["proof"]["digest"])
            self.first = self.retain(writer.export(), "first")
        finally:
            writer.close()
        self.original = self.snapshot(self.source)

    @staticmethod
    def file_state(path):
        return path.read_bytes(), path.stat().st_mtime_ns

    def reader(self, path):
        store = fixture.Store(path, self.source_commit, read_only=True)
        self.addCleanup(store.close)
        return store

    def snapshot(self, path):
        before = self.file_state(path)
        store = self.reader(path)
        try:
            rows = tuple(tuple(store.db.execute(
                f"SELECT * FROM {table} ORDER BY 1")) for table in
                ("metadata", "records", "requests"))
        finally:
            store.close()
        self.assertEqual(self.file_state(path), before)
        return before, rows

    def retain(self, envelope, name):
        # Direct local test observation, not an independently authenticated anchor.
        saved = {"envelope": envelope, "proof": envelope["proof"]["digest"],
                 "path": self.work / f"{name}.json"}
        fixture.publish_envelope(saved["path"], envelope)
        return saved

    def checkpoint(self, name):
        store = self.reader(self.source)
        try:
            return self.retain(store.export(), name)
        finally:
            store.close()

    @staticmethod
    def cleanup_child(child):
        try:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
        finally:
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()

    def line(self, child):
        deadline = time.monotonic() + 10
        line = bytearray()
        while len(line) < 80:
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, "worker IPC timeout")
            self.assertTrue(select.select([child.stdout], [], [], remaining)[0],
                            "worker did not reach barrier")
            byte = os.read(child.stdout.fileno(), 1)
            self.assertTrue(byte, "worker exited before barrier")
            if byte == b"\n":
                return line.decode("ascii")
            line.extend(byte)
        self.fail("unexpected worker output")

    def worker(self, stage):
        child = subprocess.Popen(
            [sys.executable, "-I", "-u", "-c", WORKER, str(HERE),
             str(self.source), self.source_commit, self.first["proof"], stage],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0)
        self.addCleanup(self.cleanup_child, child)
        self.assertEqual(self.line(child), "READY")
        child.stdin.write(b"GO\n")
        child.stdin.flush()
        self.assertEqual(self.line(child), stage)
        self.assertIsNone(child.poll())
        return child

    def kill(self, child):
        self.assertIsNone(child.poll())
        self.assertEqual(select.select([child.stdout], [], [], 0)[0], [],
                         "worker must emit only READY and the barrier, never a receipt")
        child.send_signal(signal.SIGKILL)
        self.assertEqual(child.wait(timeout=10), -signal.SIGKILL)
        stdout, stderr = child.communicate(timeout=10)
        self.assertEqual(stdout, b"")
        self.assertEqual(stderr, b"")

    def cli(self, args, *, error=None):
        result = subprocess.run(
            [sys.executable, "-I", *map(str, args)],
            capture_output=True, text=True, timeout=15)
        if error is not None:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn(f"ValueError: {error}", result.stderr)
            return None
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def lookup(self, path, saved, expected, *, key="second", error=None):
        output = self.work / f"{path.stem}-{key}-{saved['path'].stem}-receipt.json"
        result = self.cli([
            HERE / "fixture.py", "receipt", "--db", path,
            "--source-commit", self.source_commit, "--request-key", key,
            "--expected-proof", saved["proof"], "--receipt-output", output], error=error)
        if error is not None:
            self.assertFalse(output.exists())
            return None
        self.assertEqual(result, {
            "result": "SYNTHETIC_HISTORICAL_RECEIPT", "request_key": key,
            "source_commit": self.source_commit, "proof": saved["proof"],
            "receipt": expected, "execution": False, "authenticity": False})
        self.assertEqual(output.read_bytes(), fixture.canonical(expected) + b"\n")
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        return output

    def assert_groups(self, saved, keys, *, closed=False, path=None):
        records = saved["envelope"]["records"]
        self.assertEqual(len(records), 5 * len(keys) + int(closed))
        self.assertEqual([r["seq"] for r in records], list(range(1, len(records) + 1)))
        commits = [r for r in records if r["kind"] == "commit"]
        self.assertEqual([r["data"]["request"]["request_key"] for r in commits], keys)
        store = self.reader(path or self.source)
        try:
            self.assertEqual(store.export(expected_proof=saved["proof"]), saved["envelope"])
            mapping = list(store.db.execute("SELECT * FROM requests ORDER BY key"))
            self.assertEqual([row[0] for row in mapping], keys)
            for row, commit in zip(mapping, commits):
                self.assertEqual(row[1], commit["data"]["request_hash"])
                self.assertEqual(json.loads(row[2]), self.expected_receipt(commit))
        finally:
            store.close()
        if closed:
            self.assertEqual(records[-1]["kind"], "revocation")

    @staticmethod
    def expected_receipt(commit):
        # Derive from the observed committed record, never submit's lost return value.
        encoded = json.dumps(commit["data"]["request"], sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False).encode()
        return {"commit": commit["hash"], "request_hash": hashlib.sha256(encoded).hexdigest(),
                "historical_record_only": True, "execution": False}

    def committed_worker(self):
        child = self.worker("after_commit")
        current = self.checkpoint("committed")
        self.assert_groups(current, ["first", "second"])
        self.assertEqual(current["envelope"]["records"][:5], self.first["envelope"]["records"])
        expected = self.expected_receipt(current["envelope"]["records"][9])
        return child, current, expected

    def verify(self, current, previous, receipt_path, expected, *, key="second", review=False):
        args = [HERE / "verify.py", current["path"],
                "--expected-source-commit", self.source_commit,
                "--expected-proof", current["proof"],
                "--previous-envelope", previous["path"],
                "--expected-previous-proof", previous["proof"], "--receipt", receipt_path]
        if review:
            args.append("--review-summary")
        retained = {p: self.file_state(p) for p in
                    (current["path"], previous["path"], receipt_path)}
        result = self.cli(args)
        self.assertEqual({p: self.file_state(p) for p in retained}, retained)
        self.assertEqual(result["result"], "VERIFIED_SYNTHETIC_ONLY")
        self.assertEqual(result["proof"], current["proof"])
        self.assertEqual(result["source_commit"], self.source_commit)
        for flag in ("source_anchor_matched", "proof_anchor_matched",
                     "previous_proof_anchor_matched"):
            self.assertIs(result[flag], True)
        self.assertIs(result["execution"], False)
        self.assertIs(result["authenticity"], False)
        added = len(current["envelope"]["records"]) - len(previous["envelope"]["records"])
        self.assertEqual((result["continuity"], result["previous_records"],
                          result["added_records"]),
                         ("EXTENDED" if added else "UNCHANGED",
                          len(previous["envelope"]["records"]), added))
        self.assertEqual(result["receipt_verification"], {
            "result": "VERIFIED_HISTORICAL_RECEIPT", "request_key": key,
            "commit_sequence": 5 if key == "first" else 10,
            **expected, "authenticity": False})
        return result

    def test_sigkill_before_commit_recovers_only_original_receipt(self):
        child = self.worker("before_commit")
        visible = self.checkpoint("while-staged")
        self.assertEqual(visible["envelope"], self.first["envelope"])
        self.assertEqual(self.snapshot(self.source)[1], self.original[1])
        self.kill(child)
        # mode=ro need not repair a hot rollback journal. Explicitly allow SQLite
        # recovery here only; close immediately without submit/revoke or other mutations.
        recovery = fixture.Store(self.source, self.source_commit)
        recovery.close()
        with patch.object(fixture.Store, "submit", side_effect=AssertionError("no replay")):
            current = self.checkpoint("recovered")
            self.assertEqual(current["envelope"], self.first["envelope"])
            self.assert_groups(current, ["first"])
            self.lookup(self.source, self.first, None, error="historical receipt not found")
            receipt = self.lookup(self.source, current, self.first_receipt, key="first")
            self.verify(current, self.first, receipt, self.first_receipt, key="first")
        self.assertEqual(self.snapshot(self.source)[1], self.original[1])

    def test_sigkill_after_commit_recovers_unacknowledged_receipt_readonly(self):
        child, current, expected = self.committed_worker()
        self.kill(child)
        before = self.snapshot(self.source)
        with patch.object(fixture.Store, "submit", side_effect=AssertionError("no replay")):
            self.lookup(self.source, self.first, None, error="expected proof mismatch")
            receipt = self.lookup(self.source, current, expected)
            self.assert_groups(current, ["first", "second"])
            self.verify(current, self.first, receipt, expected)
        self.assertEqual(self.snapshot(self.source), before)

    def test_revocation_before_sigkill_preserves_historical_receipt_and_hold(self):
        child, current, expected = self.committed_worker()
        writer = fixture.Store(self.source, self.source_commit)
        try:
            writer.revoke(expected_proof=current["proof"])
            closed = self.retain(writer.export(), "closed")
        finally:
            writer.close()
        self.kill(child)
        before = self.snapshot(self.source)
        with patch.object(fixture.Store, "submit", side_effect=AssertionError("no replay")):
            self.lookup(self.source, current, None, error="expected proof mismatch")
            receipt = self.lookup(self.source, closed, expected)
            self.assert_groups(closed, ["first", "second"], closed=True)
            result = self.verify(closed, current, receipt, expected, review=True)
        summary = result["review_summary"]
        self.assertEqual(summary["revocation_sequence"], 11)
        self.assertEqual(summary["committed_requests"], 2)
        self.assertEqual(summary["release_status"], "HOLD")
        self.assertIs(summary["release_authorized"], False)
        self.assertIs(summary["execution"], False)
        self.assertIs(summary["authenticity"], False)
        self.assertEqual(self.snapshot(self.source), before)

    def test_sigkill_then_anchored_backup_recovers_same_receipt_without_restore(self):
        child, current, expected = self.committed_worker()
        self.kill(child)
        source_before = self.snapshot(self.source)
        backup = self.work / "published-copy.sqlite"
        result = self.cli([
            HERE / "fixture.py", "backup", "--db", self.source, "--backup-db", backup,
            "--source-commit", self.source_commit, "--expected-proof", current["proof"]])
        self.assertEqual(result, {
            "result": "SYNTHETIC_BACKUP_VERIFIED", "records": 10,
            "proof": current["proof"], "source_commit": self.source_commit,
            "execution": False, "authenticity": False})
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.snapshot(self.source), source_before)
        backup_before = self.snapshot(backup)
        with patch.object(fixture.Store, "submit", side_effect=AssertionError("no replay")):
            self.lookup(backup, self.first, None, error="expected proof mismatch")
            receipt = self.lookup(backup, current, expected)
            self.assert_groups(current, ["first", "second"], path=backup)
            self.verify(current, self.first, receipt, expected)
        self.assertEqual(self.snapshot(self.source), source_before)
        self.assertEqual(self.snapshot(backup), backup_before)
        self.assertEqual(list(self.work.glob(".era-*")), [])


if __name__ == "__main__":
    unittest.main()
