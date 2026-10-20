"""Integrated local recovery drills, not additional official WF mappings."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import fixture

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# Only this explicitly supplied database is opened writable in a fresh process.
PRODUCER = """
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import fixture
p = json.loads(sys.argv[4])
store = None
try:
    store = fixture.Store(sys.argv[2], sys.argv[3], read_only=False)
    exec(sys.argv[5])
    print(json.dumps(result))
except ValueError as error:
    print(json.dumps({"error": str(error)}))
    sys.exit(1)
finally:
    if store is not None:
        store.close()
"""


class IntegratedRecoveryDrill(unittest.TestCase):
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

    def tearDown(self):
        self.assertEqual(list(self.work.glob(".era-*")), [])
        self.assertEqual(list(self.work.glob("*-journal")), [])

    @staticmethod
    def snapshot(path):
        return path.read_bytes(), path.stat().st_mtime_ns

    def files(self):
        return {path.name: self.snapshot(path) for path in self.work.iterdir()}

    def run_json(self, args, *, error=None):
        completed = subprocess.run(
            [sys.executable, "-I", *map(str, args)], capture_output=True,
            text=True, timeout=15)
        self.assertEqual(completed.returncode, 0 if error is None else 1,
                         completed.stdout + completed.stderr)
        self.assertEqual(completed.stderr, "")
        value = json.loads(completed.stdout)
        if error is not None:
            self.assertEqual(value, error)
        return value

    def producer(self, path, body, *, error=None, **parameters):
        return self.run_json(
            ["-c", PRODUCER, HERE, path, self.source_commit,
             json.dumps(parameters), body], error=error)

    def checkpoint(self, store, name):
        envelope = store.export()
        # Retained directly from the producer, before backup; never read from a copy.
        saved = {"envelope": envelope, "proof": envelope["proof"]["digest"],
                 "path": self.work / f"{name}.json"}
        fixture.publish_envelope(saved["path"], envelope)
        return saved

    def seed(self, *, second=False, closed=False):
        store = fixture.Store(self.source, self.source_commit)
        try:
            empty = store.export()["proof"]["digest"]
            receipt = store.submit(fixture.request("first"), expected_proof=empty)
            first = self.checkpoint(store, "first")
            if second:
                store.submit(fixture.request("second"), expected_proof=first["proof"])
            if closed:
                store.revoke(expected_proof=store.export()["proof"]["digest"])
            current = self.checkpoint(store, "current")
        finally:
            store.close()
        self.receipt = receipt
        self.receipt_path = self.work / "receipt.json"
        self.receipt_path.write_bytes(fixture.canonical(receipt))
        return first, current

    def backup(self, source, saved, name="copy"):
        destination = self.work / f"{name}.sqlite"
        before = self.snapshot(source)
        result = self.run_json([
            HERE / "fixture.py", "backup", "--db", source,
            "--backup-db", destination, "--source-commit", self.source_commit,
            "--expected-proof", saved["proof"]])
        self.assertEqual(result, {
            "result": "SYNTHETIC_BACKUP_VERIFIED",
            "records": len(saved["envelope"]["records"]), "proof": saved["proof"],
            "source_commit": self.source_commit, "execution": False, "authenticity": False})
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.snapshot(source), before)
        return destination

    def advance(self, path, saved, name, *, closed=False):
        output = self.work / f"{name}.json"
        result = self.producer(path, """
initial = store.export(expected_proof=p["proof"])
store.submit(fixture.request(p["key"]), expected_proof=p["proof"])
envelope = store.export()
if p["closed"]:
    store.revoke(expected_proof=envelope["proof"]["digest"])
    envelope = store.export()
fixture.publish_envelope(p["output"], envelope)
result = {"initial": initial, "envelope": envelope, "proof": envelope["proof"]["digest"]}
""", proof=saved["proof"], key=name, closed=closed, output=str(output))
        self.assertEqual(result["initial"], saved["envelope"])
        self.assertEqual(result["proof"], result["envelope"]["proof"]["digest"])
        self.assertEqual(len(result["envelope"]["records"]), 11 if closed else 10)
        self.assertEqual(result["envelope"]["source"]["commit"], self.source_commit)
        return {**result, "path": output}

    def deny_writes(self, path, proof, message="expected proof mismatch"):
        for operation in (
                'store.submit(fixture.request("fresh"), expected_proof=p["proof"])',
                'store.revoke(expected_proof=p["proof"])'):
            with self.subTest(operation=operation):
                before = self.files()
                self.producer(path, operation, proof=proof, error={"error": message})
                self.assertEqual(self.files(), before)

    def export_cli(self, path, name, proof=None, *, error=None):
        output = self.work / f"{name}.json"
        args = [HERE / "fixture.py", "export", "--db", path, "--envelope", output,
                "--source-commit", self.source_commit]
        if proof is not None:
            args += ["--expected-proof", proof]
        before = self.files()
        if error is None:
            result = self.run_json(args)
            self.assertEqual(result["result"], "SYNTHETIC_READ_ONLY_EXPORT")
            self.assertIs(result["execution"], False)
            self.assertIs(result["authenticity"], False)
            self.assertTrue(output.is_file())
            self.assertEqual({k: v for k, v in self.files().items() if k != output.name},
                             before)
            return {"path": output, "proof": result["proof"]}
        completed = subprocess.run(
            [sys.executable, "-I", *map(str, args)], capture_output=True,
            text=True, timeout=15)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertEqual(completed.stdout, "")
        self.assertIn(f"ValueError: {error}", completed.stderr)
        self.assertFalse(output.exists())
        self.assertEqual(self.files(), before)

    def verify_cli(self, current, previous=None, *, receipt=False, review=False,
                   rejected=False):
        args = [HERE / "verify.py", current["path"],
                "--expected-source-commit", self.source_commit,
                "--expected-proof", current["proof"]]
        if previous is not None:
            args += ["--previous-envelope", previous["path"],
                     "--expected-previous-proof", previous["proof"]]
        if receipt:
            args += ["--receipt", self.receipt_path]
        if review:
            args += ["--review-summary"]
        before = self.files()
        result = self.run_json(args, error={"result": "REJECTED"} if rejected else None)
        self.assertEqual(self.files(), before)
        if not rejected:
            self.assertEqual(result["result"], "VERIFIED_SYNTHETIC_ONLY")
            self.assertEqual(result["proof"], current["proof"])
            self.assertEqual(result["source_commit"], self.source_commit)
            for flag in ("source_anchor_matched", "proof_anchor_matched"):
                self.assertIs(result[flag], True)
            self.assertIs(result["execution"], False)
            self.assertIs(result["authenticity"], False)
        return result

    def assert_source(self, saved, before):
        store = fixture.Store(self.source, self.source_commit, read_only=True)
        try:
            self.assertEqual(store.export(expected_proof=saved["proof"]), saved["envelope"])
        finally:
            store.close()
        self.assertEqual(self.snapshot(self.source), before)

    def assert_receipt_and_hold(self, result, records):
        receipt = result["receipt_verification"]
        self.assertEqual(receipt, {
            "result": "VERIFIED_HISTORICAL_RECEIPT", "request_key": "first",
            "commit_sequence": 5, "commit": self.receipt["commit"],
            "request_hash": self.receipt["request_hash"], "historical_record_only": True,
            "execution": False, "authenticity": False})
        summary = result["review_summary"]
        self.assertEqual(summary["records"], records)
        self.assertEqual(summary["revocation_sequence"], records)
        self.assertEqual(summary["release_status"], "HOLD")
        self.assertIs(summary["release_authorized"], False)
        self.assertIs(summary["execution"], False)
        self.assertIs(summary["authenticity"], False)
        self.assertEqual(summary["open_gates"], [
            "canonical_contract_conformance", "independent_external_verification",
            "operational_authorization", "human_release_decision"])

    def test_open_backup_recovery_through_closed_review(self):
        first, _ = self.seed()
        source_before = self.snapshot(self.source)
        retained = {p: self.snapshot(p) for p in (first["path"], self.receipt_path)}
        copy = self.backup(self.source, first)
        closed = self.advance(copy, first, "second", closed=True)
        result = self.verify_cli(closed, first, receipt=True, review=True)
        self.assertEqual((result["continuity"], result["previous_records"],
                          result["added_records"]), ("EXTENDED", 5, 6))
        self.assertIs(result["previous_proof_anchor_matched"], True)
        self.assert_receipt_and_hold(result, 11)
        self.assert_source(first, source_before)
        self.assertFalse(any(r["kind"] == "revocation" for r in first["envelope"]["records"]))
        self.assertEqual({p: self.snapshot(p) for p in retained}, retained)

    def test_stale_copy_cannot_replace_advanced_source(self):
        first, _ = self.seed()
        copy = self.backup(self.source, first)
        trusted = self.advance(self.source, first, "source-second")
        source_before = self.snapshot(self.source)
        self.deny_writes(copy, trusted["proof"])
        self.export_cli(copy, "stale-refused", trusted["proof"],
                        error="expected proof mismatch")
        stale = self.export_cli(copy, "stale", first["proof"])
        self.verify_cli(stale)
        self.verify_cli(stale, trusted, rejected=True)
        self.assert_source(trusted, source_before)

    def test_coherent_rollback_is_structural_not_trusted_continuity(self):
        first, closed = self.seed(second=True, closed=True)
        source_before = self.snapshot(self.source)
        copy = self.backup(self.source, closed)
        with sqlite3.connect(copy) as db:
            db.execute("DELETE FROM records WHERE seq>5")
            db.execute("DELETE FROM requests WHERE key=?", ("second",))
        self.deny_writes(copy, closed["proof"])
        rolled_back = self.export_cli(copy, "rolled-back")
        self.assertEqual(rolled_back["proof"], first["proof"])
        self.assertEqual(self.verify_cli(rolled_back)["records"], 5)
        self.verify_cli(rolled_back, closed, rejected=True)
        self.assert_source(closed, source_before)

    def test_revoked_recovery_only_allows_historical_noops(self):
        _, closed = self.seed(closed=True)
        source_before = self.snapshot(self.source)
        retained = {p: self.snapshot(p) for p in (closed["path"], self.receipt_path)}
        copy = self.backup(self.source, closed)
        copy_before = self.snapshot(copy)
        recovered = self.work / "recovered.json"
        result = self.producer(copy, """
initial = store.export(expected_proof=p["proof"])
receipt = store.submit(fixture.request("first"), expected_proof=p["proof"])
try:
    store.submit(fixture.request("fresh"), expected_proof=p["proof"])
except ValueError as error:
    denied = str(error)
else:
    raise AssertionError("revoked copy admitted a fresh request")
store.revoke(expected_proof=p["proof"])
envelope = store.export(expected_proof=p["proof"])
fixture.publish_envelope(p["output"], envelope)
result = {"receipt": receipt, "denied": denied, "envelope": envelope,
          "proof": envelope["proof"]["digest"], "initial": initial}
""", proof=closed["proof"], output=str(recovered))
        self.assertEqual(result["denied"], "synthetic authority revoked")
        self.assertEqual(result["receipt"], self.receipt)
        self.assertIs(result["receipt"]["historical_record_only"], True)
        self.assertIs(result["receipt"]["execution"], False)
        self.assertEqual(result["initial"], closed["envelope"])
        self.assertEqual(result["envelope"], closed["envelope"])
        self.assertEqual(result["proof"], closed["proof"])
        self.assertEqual(self.snapshot(copy), copy_before)
        checked = self.verify_cli({**result, "path": recovered}, closed,
                                  receipt=True, review=True)
        self.assertEqual((checked["continuity"], checked["previous_records"],
                          checked["added_records"]), ("UNCHANGED", 6, 0))
        self.assert_receipt_and_hold(checked, 6)
        self.assert_source(closed, source_before)
        self.assertEqual({p: self.snapshot(p) for p in retained}, retained)

    def test_wrong_anchor_and_corrupt_copy_refuse_publication(self):
        first, _ = self.seed()
        source_before = self.snapshot(self.source)
        trusted_before = self.snapshot(first["path"])
        self.export_cli(self.source, "wrong-proof", "0" * 64,
                        error="expected proof mismatch")
        destination = self.work / "wrong-backup.sqlite"
        before = self.files()
        completed = subprocess.run([
            sys.executable, "-I", str(HERE / "fixture.py"), "backup",
            "--db", str(self.source), "--backup-db", str(destination),
            "--source-commit", self.source_commit, "--expected-proof", "0" * 64],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertEqual(completed.stdout, "")
        self.assertIn("ValueError: expected proof mismatch", completed.stderr)
        self.assertFalse(destination.exists())
        self.assertEqual(self.files(), before)
        copy = self.backup(self.source, first)
        with sqlite3.connect(copy) as db:
            db.execute("UPDATE requests SET receipt=?", ("{}",))
        self.export_cli(copy, "corrupt-export", first["proof"],
                        error="persisted receipt mismatch")
        before = self.files()
        self.producer(copy,
                      'result = store.submit(fixture.request("first"), expected_proof=p["proof"])',
                      proof=first["proof"], error={"error": "persisted receipt mismatch"})
        self.assertEqual(self.files(), before)
        self.assert_source(first, source_before)
        self.assertEqual(self.snapshot(first["path"]), trusted_before)

    def test_two_explicit_recoveries_can_fork_but_not_pass_continuity(self):
        first, _ = self.seed()
        source_before = self.snapshot(self.source)
        trusted_before = self.snapshot(first["path"])
        left = self.backup(self.source, first, "left")
        right = self.backup(self.source, first, "right")
        left_checkpoint = self.advance(left, first, "left-second")
        right_checkpoint = self.advance(right, first, "right-second")
        self.assertNotEqual(left_checkpoint["proof"], right_checkpoint["proof"])
        for checkpoint in (left_checkpoint, right_checkpoint):
            checked = self.verify_cli(checkpoint, first)
            self.assertEqual((checked["continuity"], checked["previous_records"],
                              checked["added_records"]), ("EXTENDED", 5, 5))
        self.verify_cli(right_checkpoint, left_checkpoint, rejected=True)
        self.verify_cli(left_checkpoint, right_checkpoint, rejected=True)
        self.assert_source(first, source_before)
        self.assertEqual(self.snapshot(first["path"]), trusted_before)


if __name__ == "__main__":
    unittest.main()
