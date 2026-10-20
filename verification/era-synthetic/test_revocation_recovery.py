"""Local revocation crash evidence, not power-loss or official conformance proof."""
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
store.revoke(expected_proof=sys.argv[4], _checkpoint=checkpoint)
raise RuntimeError("revocation unexpectedly returned")
"""


class RevocationRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True, timeout=10).stdout.strip()
        if len(cls.source) != 40:
            raise AssertionError("requires actual 40-hex HEAD")

    def setUp(self):
        runtime = HERE / ".runtime"
        runtime.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.path = self.work / "state.sqlite"
        store = self.writer()
        try:
            self.receipt = store.submit(
                fixture.request("first"), expected_proof=store.export()["proof"]["digest"])
            self.initial = store.export()
        finally:
            store.close()
        # Retained local observations are not independently authenticated anchors.
        self.open_path = self.work / "open.json"
        self.receipt_path = self.work / "receipt.json"
        fixture.publish_envelope(self.open_path, self.initial)
        fixture.publish_envelope(self.receipt_path, self.receipt)
        self.proof = self.initial["proof"]["digest"]
        self.original_mapping = self.observe(self.initial)

    def writer(self):
        return fixture.Store(self.path, self.source)

    def observe(self, expected):
        store = fixture.Store(self.path, self.source, read_only=True)
        try:
            self.assertEqual(store.export(expected_proof=expected["proof"]["digest"]), expected)
            self.assertEqual(store.lookup_receipt(
                "first", expected_proof=expected["proof"]["digest"]), self.receipt)
            mapping = list(store.db.execute("SELECT * FROM requests ORDER BY key"))
            self.assertEqual(len(mapping), 1)
            self.assertEqual(mapping[0][0], "first")
            self.assertEqual(mapping[0][1], self.receipt["request_hash"])
            self.assertEqual(json.loads(mapping[0][2]), self.receipt)
            return mapping
        finally:
            store.close()

    def closed(self):
        store = fixture.Store(self.path, self.source, read_only=True)
        try:
            envelope = store.export()
        finally:
            store.close()
        self.assertEqual(envelope["records"][:5], self.initial["records"])
        self.assertEqual(len(envelope["records"]), 6)
        self.assertEqual(envelope["records"][-1], {
            "seq": 6, "kind": "revocation",
            "data": {"authority": fixture.FIXED["authority"], "execution": False},
            "prev": self.initial["records"][-1]["hash"],
            "hash": fixture.digest({k: envelope["records"][-1][k]
                                    for k in ("seq", "kind", "data", "prev")})})
        self.assertEqual(self.observe(envelope), self.original_mapping)
        return envelope

    def files(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.work.iterdir() if p.is_file()}

    def check(self, envelope, *, review=False):
        current = self.work / "current.json"
        fixture.publish_envelope(current, envelope)
        before = self.files()
        args = [sys.executable, "-I", str(HERE / "verify.py"), str(current),
                "--expected-source-commit", self.source,
                "--expected-proof", envelope["proof"]["digest"],
                "--previous-envelope", str(self.open_path),
                "--expected-previous-proof", self.proof,
                "--receipt", str(self.receipt_path), "--expected-request-key", "first"]
        if review:
            args.append("--review-summary")
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.files(), before)
        value = json.loads(result.stdout)
        self.assertEqual(value["result"], "VERIFIED_SYNTHETIC_ONLY")
        self.assertEqual(value["proof"], envelope["proof"]["digest"])
        self.assertEqual(value["source_commit"], self.source)
        for key in ("source_anchor_matched", "proof_anchor_matched",
                    "previous_proof_anchor_matched"):
            self.assertIs(value[key], True)
        self.assertIs(value["execution"], False)
        self.assertIs(value["authenticity"], False)
        self.assertEqual((value["continuity"], value["previous_records"],
                          value["added_records"]),
                         ("EXTENDED" if review else "UNCHANGED", 5, int(review)))
        self.assertEqual(value["receipt_verification"], {
            "result": "VERIFIED_HISTORICAL_RECEIPT", "request_key": "first",
            "commit_sequence": 5, **self.receipt, "authenticity": False,
            "expected_request_key": "first", "request_key_anchor_supplied": True,
            "request_key_anchor_matched": True})
        if review:
            summary = value["review_summary"]
            self.assertEqual(summary["revocation_sequence"], 6)
            self.assertEqual(summary["committed_requests"], 1)
            self.assertEqual(summary["release_status"], "HOLD")
            for key in ("release_authorized", "execution", "authenticity"):
                self.assertIs(summary[key], False)

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
             str(self.path), self.source, self.proof, stage],
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
        self.assertEqual(select.select([child.stdout], [], [], 0)[0], [])
        child.send_signal(signal.SIGKILL)
        self.assertEqual(child.wait(timeout=10), -signal.SIGKILL)
        self.assertEqual(child.communicate(timeout=10), (b"", b""))

    def stale_and_denied(self, closed):
        store = self.writer()
        try:
            for operation in (
                    lambda: store.revoke(expected_proof=self.proof),
                    lambda: store.submit(fixture.request("new"), expected_proof=self.proof)):
                with self.assertRaisesRegex(ValueError, "expected proof mismatch"):
                    operation()
                self.assertFalse(store.db.in_transaction)
            with self.assertRaisesRegex(ValueError, "synthetic authority revoked"):
                store.submit(fixture.request("new"), expected_proof=closed["proof"]["digest"])
            stages = []
            store.revoke(expected_proof=closed["proof"]["digest"], _checkpoint=stages.append)
            self.assertEqual(stages, ["before_commit", "after_commit"])
            self.assertEqual(store.export(), closed)
        finally:
            store.close()
        self.observe(closed)

    @unittest.skipUnless(hasattr(signal, "SIGKILL"), "requires SIGKILL")
    def test_sigkill_before_commit_rolls_back_then_allows_guarded_revocation(self):
        child = self.worker("before_commit")
        self.assertEqual(self.observe(self.initial), self.original_mapping)
        self.kill(child)
        # Read-only opens need not repair a hot journal: explicitly allow recovery.
        recovery = self.writer()
        recovery.close()
        before = self.files()
        self.assertEqual(self.observe(self.initial), self.original_mapping)
        self.assertEqual(self.files(), before)
        self.check(self.initial)
        store = self.writer()
        try:
            store.revoke(expected_proof=self.proof)
        finally:
            store.close()
        self.stale_and_denied(self.closed())

    @unittest.skipUnless(hasattr(signal, "SIGKILL"), "requires SIGKILL")
    def test_sigkill_after_commit_preserves_closed_checkpoint_without_replay(self):
        child = self.worker("after_commit")
        closed = self.closed()
        self.kill(child)
        before = self.files()
        with patch.object(fixture.Store, "submit", side_effect=AssertionError("no replay")):
            self.assertEqual(self.closed(), closed)
            reader = fixture.Store(self.path, self.source, read_only=True)
            try:
                for operation in (
                        lambda: reader.export(expected_proof=self.proof),
                        lambda: reader.lookup_receipt("first", expected_proof=self.proof)):
                    with self.assertRaisesRegex(ValueError, "expected proof mismatch"):
                        operation()
            finally:
                reader.close()
        self.assertEqual(self.files(), before)
        self.check(closed, review=True)
        self.stale_and_denied(closed)

    def test_before_commit_callback_error_rolls_back_and_closes_transaction(self):
        store = self.writer()
        stages = []
        def fail(stage):
            stages.append(stage)
            self.assertTrue(store.db.in_transaction)
            self.assertEqual(store.db.execute("SELECT count(*) FROM records").fetchone()[0], 6)
            raise RuntimeError("callback failed")
        try:
            with self.assertRaisesRegex(RuntimeError, "callback failed"):
                store.revoke(expected_proof=self.proof, _checkpoint=fail)
            self.assertEqual(stages, ["before_commit"])
            self.assertFalse(store.db.in_transaction)
            self.assertEqual(store.export(), self.initial)
        finally:
            store.close()
        self.assertEqual(self.observe(self.initial), self.original_mapping)

    def test_after_commit_callback_error_cannot_undo_durable_revocation(self):
        store = self.writer()
        stages = []
        def fail(stage):
            stages.append(stage)
            self.assertEqual(store.db.in_transaction, stage == "before_commit")
            if stage == "after_commit":
                raise RuntimeError("acknowledgement failed")
        try:
            with self.assertRaisesRegex(RuntimeError, "acknowledgement failed"):
                store.revoke(expected_proof=self.proof, _checkpoint=fail)
            self.assertEqual(stages, ["before_commit", "after_commit"])
            self.assertFalse(store.db.in_transaction)
        finally:
            store.close()
        closed = self.closed()
        self.check(closed, review=True)
        self.stale_and_denied(closed)

    def test_guards_and_full_validation_reject_before_checkpoint(self):
        store = self.writer()
        stages = []
        try:
            for proof in (None, "", "A" * 64, "g" * 64, "a" * 63, True, {}, b"a" * 64):
                with self.subTest(proof=proof), self.assertRaisesRegex(
                        ValueError, "expected proof must"):
                    store.revoke(expected_proof=proof, _checkpoint=stages.append)
                self.assertFalse(store.db.in_transaction)
            with self.assertRaisesRegex(ValueError, "expected proof mismatch"):
                store.revoke(expected_proof="0" * 64, _checkpoint=stages.append)
            with patch.object(store, "_validate_state", side_effect=ValueError("invalid state")):
                with self.assertRaisesRegex(ValueError, "invalid state"):
                    store.revoke(expected_proof=self.proof, _checkpoint=stages.append)
            self.assertFalse(store.db.in_transaction)
        finally:
            store.close()
        reader = fixture.Store(self.path, self.source, read_only=True)
        try:
            with self.assertRaisesRegex(ValueError, "read-only store"):
                reader.revoke(expected_proof=self.proof, _checkpoint=stages.append)
        finally:
            reader.close()
        self.assertEqual(stages, [])
        self.observe(self.initial)

    def test_omitted_proof_and_idempotent_callbacks_preserve_original_receipt(self):
        store = self.writer()
        stages = []
        try:
            store.revoke(_checkpoint=stages.append)
            closed = store.export()
            store.revoke(_checkpoint=stages.append)
            self.assertEqual(store.export(), closed)
            self.assertEqual(stages, ["before_commit", "after_commit"] * 2)
        finally:
            store.close()
        self.assertEqual(self.closed(), closed)

    def test_no_checkpoint_cli_or_serialized_request_control(self):
        for option in ("--checkpoint", "--_checkpoint", "--fault"):
            db = self.work / "must-not-exist.sqlite"
            result = subprocess.run(
                [sys.executable, "-I", str(HERE / "fixture.py"), "demo", "--db", str(db),
                 "--envelope", str(self.work / "absent.json"),
                 "--source-commit", self.source, option, "before_commit"],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments", result.stderr)
            self.assertFalse(db.exists())
            self.assertFalse((self.work / "absent.json").exists())
        store = self.writer()
        try:
            for field in ("checkpoint", "_checkpoint", "fault"):
                value = fixture.request("new")
                value[field] = "before_commit"
                with self.assertRaises(ValueError):
                    store.submit(value)
            self.assertEqual(store.export(), self.initial)
        finally:
            store.close()
        self.observe(self.initial)


if __name__ == "__main__":
    unittest.main()
