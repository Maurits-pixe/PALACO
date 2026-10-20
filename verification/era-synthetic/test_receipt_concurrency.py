"""Local SQLite snapshot/lock evidence, not global freshness or authorization."""
import json
import multiprocessing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

import fixture

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40  # Artificial local checkpoint, not an authenticated source anchor.


def receipt_reader(path, proof, channel):
    store = None
    try:
        store = fixture.Store(path, SOURCE, read_only=True)
        trace = []
        store.db.set_trace_callback(trace.append)
        original = store._check_expected_proof

        def pinned(records, expected):
            envelope = original(records, expected)
            channel.send(("snapshot_pinned", envelope["proof"]["digest"],
                          len(records), store.db.in_transaction))
            if not channel.poll(10) or channel.recv() != "resume":
                raise RuntimeError("reader control timeout or invalid resume")
            return envelope

        store._check_expected_proof = pinned
        receipt = store.lookup_receipt("first", expected_proof=proof)
        channel.send(("result", receipt, proof, trace, store.db.total_changes,
                      store.db.in_transaction))
    except BaseException as error:
        channel.send(("error", type(error).__name__, str(error)))
    finally:
        if store is not None:
            store.close()
        channel.close()


def receipt_writer(path, proof, operation, channel):
    store = None
    try:
        store = fixture.Store(path, SOURCE)
        channel.send(("writer_ready",))
        if not channel.poll(10) or channel.recv() != "write":
            raise RuntimeError("writer control timeout or invalid command")

        def attempting(sql):
            if sql == "COMMIT":
                channel.send(("commit_attempt",))

        # Exclude the constructor's independent validation transaction.
        store.db.set_trace_callback(attempting)
        if operation == "submit":
            outcome = store.submit(fixture.request("second"), expected_proof=proof)
        else:
            outcome = store.revoke(expected_proof=proof)
        store.db.set_trace_callback(None)
        channel.send(("result", outcome, store.export()))
    except BaseException as error:
        channel.send(("error", type(error).__name__, str(error)))
    finally:
        if store is not None:
            store.close()
        channel.close()


class ReceiptConcurrency(unittest.TestCase):
    def setUp(self):
        runtime = HERE / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.path = self.work / "source.sqlite"
        store = fixture.Store(self.path, SOURCE)
        try:
            self.receipt = store.submit(fixture.request("first"))
            self.first = store.export()
        finally:
            store.close()
        self.proof = self.first["proof"]["digest"]
        self.previous_path = self.work / "first.json"
        fixture.publish_envelope(self.previous_path, self.first)

    def reader(self):
        store = fixture.Store(self.path, SOURCE, read_only=True)
        self.addCleanup(store.close)
        self.assertEqual(store.db.execute("PRAGMA busy_timeout").fetchone(), (2000,))
        self.assertEqual(store.db.total_changes, 0)
        return store

    def file_state(self):
        return self.path.read_bytes(), self.path.stat().st_mtime_ns

    def rows(self):
        store = self.reader()
        try:
            return tuple(tuple(store.db.execute(f"SELECT * FROM {table} ORDER BY 1"))
                         for table in ("metadata", "records", "requests"))
        finally:
            store.close()

    def assert_readonly(self, store, trace):
        self.assertFalse(store.db.in_transaction)
        self.assertEqual(store.db.total_changes, 0)
        self.assert_trace(trace)

    def assert_trace(self, trace):
        self.assertTrue(trace)
        self.assertEqual(trace[0], "BEGIN")
        self.assertTrue(all(sql.split()[0] in ("BEGIN", "SELECT", "COMMIT", "ROLLBACK")
                            for sql in trace), trace)
        self.assertNotIn("BEGIN IMMEDIATE", trace)

    @staticmethod
    def cleanup_worker(process, channel):
        try:
            if process.is_alive():
                process.kill()
            process.join(timeout=10)
            if process.is_alive():
                raise AssertionError("child did not exit after kill")
        finally:
            channel.close()
            if not process.is_alive():
                process.close()

    def worker(self, target, *arguments):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=target, args=(*arguments, child))
        try:
            process.start()
        except BaseException:
            parent.close()
            child.close()
            raise
        child.close()
        self.addCleanup(self.cleanup_worker, process, parent)
        return process, parent

    def receive(self, channel):
        self.assertTrue(channel.poll(10), "worker IPC deadline exceeded")
        return channel.recv()

    def assert_exited(self, process):
        process.join(timeout=10)
        self.assertFalse(process.is_alive(), "worker did not finish")
        self.assertEqual(process.exitcode, 0)

    def verify_current(self, envelope, *, closed):
        current_path = self.work / "current.json"
        receipt_path = self.work / "receipt.json"
        fixture.publish_envelope(current_path, envelope)
        fixture.publish_envelope(receipt_path, self.receipt)
        retained = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in (current_path, self.previous_path, receipt_path)}
        args = [
            sys.executable, "-I", str(HERE / "verify.py"), str(current_path),
            "--expected-source-commit", SOURCE,
            "--expected-proof", envelope["proof"]["digest"],
            "--previous-envelope", str(self.previous_path),
            "--expected-previous-proof", self.proof,
            "--receipt", str(receipt_path), "--expected-request-key", "first"]
        if closed:
            args.append("--review-summary")
        checked = subprocess.run(args, capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual(checked.stderr, "")
        result = json.loads(checked.stdout)
        self.assertEqual(result["result"], "VERIFIED_SYNTHETIC_ONLY")
        self.assertEqual(result["source_commit"], SOURCE)
        self.assertEqual(result["proof"], envelope["proof"]["digest"])
        self.assertEqual(result["previous_proof"], self.proof)
        for flag in ("source_anchor_matched", "proof_anchor_matched",
                     "previous_proof_anchor_matched"):
            self.assertIs(result[flag], True)
        self.assertEqual((result["continuity"], result["previous_records"],
                          result["added_records"]), ("EXTENDED", 5, 1 if closed else 5))
        self.assertIs(result["execution"], False)
        self.assertIs(result["authenticity"], False)
        self.assertEqual(result["receipt_verification"], {
            "result": "VERIFIED_HISTORICAL_RECEIPT", "request_key": "first",
            "commit_sequence": 5, **self.receipt, "authenticity": False,
            "expected_request_key": "first", "request_key_anchor_supplied": True,
            "request_key_anchor_matched": True})
        if closed:
            summary = result["review_summary"]
            self.assertEqual((summary["records"], summary["committed_requests"],
                              summary["revocation_sequence"]), (6, 1, 6))
            self.assertEqual(summary["release_status"], "HOLD")
            for flag in ("release_authorized", "execution", "authenticity"):
                self.assertIs(summary[flag], False)
        else:
            self.assertNotIn("review_summary", result)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in retained},
                         retained)

    def competing_write(self, operation):
        # Constructor CREATE TABLE IF NOT EXISTS makes even its no-op COMMIT
        # require an exclusive lock. Finish opening before pinning the reader;
        # only the ordinary submit/revoke competes with the read snapshot.
        writer, events = self.worker(receipt_writer, self.path, self.proof, operation)
        self.assertEqual(self.receive(events), ("writer_ready",))
        reader, control = self.worker(receipt_reader, self.path, self.proof)
        self.assertEqual(self.receive(control), ("snapshot_pinned", self.proof, 5, True))
        events.send("write")
        marker = self.receive(events)
        # Trace announces the COMMIT attempt, not entry into a blocked native call.
        # Hand off immediately, comfortably inside SQLite's unchanged busy timeout.
        control.send("resume")
        self.assertEqual(marker, ("commit_attempt",))
        found = self.receive(control)
        written = self.receive(events)
        self.assert_exited(reader)
        self.assert_exited(writer)
        self.assertEqual(found[0], "result", found)
        self.assertEqual(written[0], "result", written)
        self.assertEqual(found[1:3], (self.receipt, self.proof))
        self.assert_trace(found[3])
        self.assertEqual(found[3][-1], "COMMIT")
        self.assertTrue(found[3][-2].startswith("SELECT receipt,typeof(receipt)"))
        self.assertEqual(found[4:], (0, False))
        closed = operation == "revoke"
        outcome, current = written[1:]
        records = current["records"]
        proof = current["proof"]["digest"]
        self.assertNotEqual(proof, self.proof)
        self.assertEqual(len(records), 6 if closed else 10)
        self.assertEqual([r["seq"] for r in records], list(range(1, len(records) + 1)))
        self.assertEqual(records[:5], self.first["records"])
        commits = [r for r in records if r["kind"] == "commit"]
        self.assertEqual([r["data"]["request"]["request_key"] for r in commits],
                         ["first"] if closed else ["first", "second"])
        if closed:
            self.assertIsNone(outcome)
            self.assertEqual(records[-1]["kind"], "revocation")
        else:
            self.assertEqual(outcome, {
                "commit": records[-1]["hash"],
                "request_hash": records[-1]["data"]["request_hash"],
                "historical_record_only": True, "execution": False})
        # Baseline only after the successful writer exits, before read-only checks.
        before = self.file_state()
        rows = self.rows()
        self.assertEqual(len(rows[1]), len(records))
        self.assertEqual([row[0] for row in rows[2]],
                         ["first"] if closed else ["first", "second"])
        original = [json.loads(row[2]) for row in rows[2] if row[0] == "first"]
        self.assertEqual(original, [self.receipt])
        store = self.reader()
        trace = []
        store.db.set_trace_callback(trace.append)
        with self.assertRaisesRegex(ValueError, "expected proof mismatch"):
            store.lookup_receipt("first", expected_proof=self.proof)
        self.assertFalse(store.db.in_transaction)
        self.assertEqual(store.lookup_receipt("first", expected_proof=proof), self.receipt)
        self.assertEqual(store.export(expected_proof=proof), current)
        self.assert_readonly(store, trace)
        store.close()
        self.verify_current(current, closed=closed)
        self.assertEqual(self.rows(), rows)
        self.assertEqual(self.file_state(), before)

    def test_snapshot_spans_validation_and_lookup_during_submit(self):
        self.competing_write("submit")

    def test_snapshot_spans_validation_and_lookup_during_revocation(self):
        self.competing_write("revoke")

    def test_exclusive_lock_failure_rolls_back_and_same_reader_recovers(self):
        before, rows = self.file_state(), self.rows()
        store = self.reader()
        trace = []
        store.db.set_trace_callback(trace.append)
        other = sqlite3.connect(self.path, isolation_level=None)
        try:
            other.execute("BEGIN EXCLUSIVE")
            started = time.monotonic()
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                store.lookup_receipt("first", expected_proof=self.proof)
            self.assertLess(time.monotonic() - started, 8)
            self.assert_readonly(store, trace)
            self.assertEqual(trace[-1], "ROLLBACK")
        finally:
            other.rollback()
            other.close()
        self.assertEqual(store.lookup_receipt("first", expected_proof=self.proof), self.receipt)
        with self.assertRaisesRegex(ValueError, "expected proof mismatch"):
            store.lookup_receipt("first", expected_proof="0" * 64)
        self.assert_readonly(store, trace)
        self.assertEqual(self.rows(), rows)
        self.assertEqual(self.file_state(), before)

    def test_reserved_lock_hides_uncommitted_mapping_deletion_without_repair(self):
        before, rows = self.file_state(), self.rows()
        store = self.reader()
        trace = []
        store.db.set_trace_callback(trace.append)
        other = sqlite3.connect(self.path, isolation_level=None)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("DELETE FROM requests WHERE key=?", ("first",))
            self.assertEqual(other.execute("SELECT count(*) FROM requests").fetchone(), (0,))
            self.assertEqual(store.lookup_receipt("first", expected_proof=self.proof),
                             self.receipt)
            self.assertEqual(store.export(expected_proof=self.proof), self.first)
            self.assert_readonly(store, trace)
        finally:
            other.rollback()
            other.close()
        self.assertEqual(store.lookup_receipt("first", expected_proof=self.proof), self.receipt)
        self.assert_readonly(store, trace)
        self.assertEqual(self.rows(), rows)
        self.assertEqual(self.file_state(), before)


if __name__ == "__main__":
    unittest.main()
