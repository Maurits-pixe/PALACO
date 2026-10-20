"""Synthetic current-snapshot mutation preconditions, never execution authority."""
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fixture
import verify

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40


def guarded_worker(path, proof, operation, key, channel):
    store = None
    try:
        store = fixture.Store(path, SOURCE)
        channel.send(("ready", None))
        if channel.recv() != "go":
            raise ValueError("unexpected barrier message")
        try:
            if operation == "submit":
                store.submit(fixture.request(key), expected_proof=proof)
            else:
                store.revoke(expected_proof=proof)
            channel.send(("success", None))
        except ValueError as error:
            channel.send(("rejected", str(error)))
    except BaseException as error:
        channel.send(("error", repr(error)))
    finally:
        if store is not None:
            store.close()
        channel.close()


class Preconditions(unittest.TestCase):
    def setUp(self):
        work = HERE / ".runtime"
        work.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.path = self.work / "state.sqlite"
        self.store = fixture.Store(self.path, SOURCE)
        self.addCleanup(self.store.close)

    def envelope(self):
        envelope = self.store.export()
        body = {k: envelope[k] for k in ("schema", "source", "flags", "records")}
        self.assertEqual(envelope["proof"]["digest"], verify.sha(body))
        return envelope

    def proof(self):
        return self.envelope()["proof"]["digest"]

    def snapshot(self):
        return (self.path.read_bytes(),
                tuple(self.store.db.execute("SELECT * FROM records ORDER BY seq")),
                tuple(self.store.db.execute("SELECT * FROM requests ORDER BY key")),
                tuple(self.store.db.execute("SELECT * FROM metadata")),
                self.store.db.total_changes)

    def unchanged(self, operation, message=None, *, healthy=True):
        before = self.snapshot()
        envelope = self.envelope() if healthy else None
        if message is None:
            result = operation()
        else:
            with self.assertRaisesRegex(ValueError, message):
                operation()
            result = None
        self.assertFalse(self.store.db.in_transaction)
        if healthy:
            self.assertEqual(self.envelope(), envelope)
        self.assertEqual(self.snapshot(), before)
        return result

    def checked(self, *, separate=False):
        envelope = self.envelope()
        path = self.work / "envelope.json"
        path.write_bytes(fixture.canonical(envelope))
        proof = envelope["proof"]["digest"]
        result = verify.verify(path, expected_source_commit=SOURCE, expected_proof=proof)
        self.assertEqual(result["records"], len(envelope["records"]))
        self.assertIs(result["execution"], False)
        self.assertIs(result["authenticity"], False)
        if separate:
            process = subprocess.run(
                [sys.executable, "-I", str(HERE / "verify.py"), str(path),
                 "--expected-source-commit", SOURCE, "--expected-proof", proof],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(json.loads(process.stdout)["records"], result["records"])
        return envelope

    def test_empty_snapshot_can_guard_first_group(self):
        empty = self.envelope()
        self.assertEqual(empty["records"], [])
        path = self.work / "empty.json"
        path.write_bytes(fixture.canonical(empty))
        with self.assertRaises(ValueError):
            verify.verify(path)
        self.store.submit(fixture.request(), expected_proof=empty["proof"]["digest"])
        self.assertEqual(len(self.checked()["records"]), 5)

    def test_guarded_submit_revoke_share_export_digest_without_nested_export(self):
        anchor = self.proof()
        with patch.object(self.store, "export", side_effect=AssertionError("nested export")):
            receipt = self.store.submit(fixture.request(), expected_proof=anchor)
        self.assertIs(receipt["historical_record_only"], True)
        current = self.proof()
        self.assertNotEqual(current, anchor)
        self.assertEqual(self.store.export(expected_proof=current), self.envelope())
        with patch.object(self.store, "export", side_effect=AssertionError("nested export")):
            self.store.revoke(expected_proof=current)
        self.assertEqual(len(self.checked()["records"]), 6)

    def test_omitted_anchor_preserves_historical_retries_and_idempotent_revoke(self):
        value = fixture.request()
        receipt = self.store.submit(value)
        self.assertEqual(self.unchanged(lambda: self.store.submit(value)), receipt)
        self.store.revoke()
        self.assertEqual(self.unchanged(lambda: self.store.submit(value)), receipt)
        self.unchanged(self.store.revoke)
        self.unchanged(lambda: self.store.submit(fixture.request("new")),
                       "synthetic authority revoked")
        self.checked()

    def test_strict_malformed_anchors_reject_before_any_sql(self):
        class Text(str):
            pass

        for anchor in (None, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64,
                       "a" * 64 + "\n", " " + "a" * 64, 0, True, [], {},
                       b"a" * 64, Text("a" * 64)):
            for name in ("submit", "revoke", "export"):
                with self.subTest(anchor=anchor, operation=name):
                    before = self.snapshot()
                    statements = []
                    self.store.db.set_trace_callback(statements.append)
                    try:
                        with self.assertRaisesRegex(ValueError, "lowercase 64-hex string"):
                            method = getattr(self.store, name)
                            args = (None,) if name == "submit" else ()
                            method(*args, expected_proof=anchor)
                    finally:
                        self.store.db.set_trace_callback(None)
                    self.assertEqual(statements, [])
                    self.assertEqual(self.snapshot(), before)

    def test_readonly_rejection_precedes_anchor_validation(self):
        readonly = fixture.Store(self.path, SOURCE, read_only=True)
        self.addCleanup(readonly.close)
        for anchor in (None, "0" * 64, self.proof()):
            for name in ("submit", "revoke"):
                with self.subTest(anchor=anchor, operation=name):
                    statements = []
                    readonly.db.set_trace_callback(statements.append)
                    try:
                        with self.assertRaisesRegex(ValueError, "read-only store"):
                            args = (None,) if name == "submit" else ()
                            getattr(readonly, name)(*args, expected_proof=anchor)
                    finally:
                        readonly.db.set_trace_callback(None)
                    self.assertEqual(statements, [])

    def test_preconditions_are_keyword_only(self):
        anchor = self.proof()
        with self.assertRaises(TypeError):
            self.store.submit(fixture.request(), anchor)
        with self.assertRaises(TypeError):
            self.store.revoke(anchor)
        self.assertEqual(self.envelope()["records"], [])

    def test_stale_exact_retry_rejected_before_and_after_revocation(self):
        value = fixture.request("first")
        receipt = self.store.submit(value)
        anchor = self.proof()
        self.store.submit(fixture.request("second"))
        for revoked in (False, True):
            with self.subTest(revoked=revoked):
                if revoked:
                    self.store.revoke()
                self.unchanged(lambda: self.store.submit(value, expected_proof=anchor),
                               "expected proof mismatch")
                self.assertEqual(self.unchanged(lambda: self.store.submit(value)), receipt)
        self.checked()

    def test_matching_anchor_historical_retry_never_renews_authority(self):
        value = fixture.request()
        receipt = self.store.submit(value)
        self.assertEqual(self.unchanged(
            lambda: self.store.submit(value, expected_proof=self.proof())), receipt)
        self.store.revoke(expected_proof=self.proof())
        anchor = self.proof()
        replay = self.unchanged(lambda: self.store.submit(value, expected_proof=anchor))
        self.assertEqual(replay, receipt)
        self.assertIs(replay["historical_record_only"], True)
        self.assertIs(replay["execution"], False)
        self.unchanged(lambda: self.store.submit(
            fixture.request("new"), expected_proof=anchor), "synthetic authority revoked")
        self.checked()

    def test_repeated_revoke_requires_current_anchor(self):
        self.store.submit(fixture.request())
        anchor = self.proof()
        self.store.revoke(expected_proof=anchor)
        current = self.proof()
        self.unchanged(lambda: self.store.revoke(expected_proof=anchor),
                       "expected proof mismatch")
        self.unchanged(lambda: self.store.revoke(expected_proof=current))
        self.checked()

    def test_stale_anchor_precedes_conflict_invalid_request_and_revoked(self):
        anchor = self.proof()
        value = fixture.request()
        self.store.submit(value)
        conflict = {**value, "action": "wrong"}
        for revoked in (False, True):
            if revoked:
                self.store.revoke()
            for payload in (conflict, None, {}, fixture.request("fresh")):
                with self.subTest(revoked=revoked, payload=payload):
                    self.unchanged(lambda: self.store.submit(
                        payload, expected_proof=anchor), "expected proof mismatch")
            self.unchanged(lambda: self.store.revoke(expected_proof=anchor),
                           "expected proof mismatch")
        self.checked()

    def test_matching_anchor_preserves_request_errors(self):
        value = fixture.request()
        self.store.submit(value)
        anchor = self.proof()
        for payload, message in (
                ({**value, "action": "wrong"}, "request key conflict"),
                (None, "unsupported request"),
                ({}, "unsupported request"),
                ({**fixture.request("fresh"), "action": "wrong"}, "denied synthetic fixture")):
            with self.subTest(payload=payload):
                self.unchanged(lambda: self.store.submit(
                    payload, expected_proof=anchor), message)
        self.checked()

    def test_corrupt_request_mapping_rejects_even_matching_envelope_proof(self):
        self.store.submit(fixture.request())
        anchor = self.proof()
        self.store.db.execute("UPDATE requests SET request_hash=?", ("0" * 64,))
        for method in (lambda: self.store.submit(fixture.request(), expected_proof=anchor),
                       lambda: self.store.revoke(expected_proof=anchor)):
            self.unchanged(method, "persisted receipt mismatch", healthy=False)

    def test_corrupt_chain_rejects_even_recalculated_matching_proof(self):
        self.store.submit(fixture.request())
        envelope = self.envelope()
        record = envelope["records"][0]
        record["data"]["identity"] = "corrupt"
        self.store.db.execute("UPDATE records SET body=? WHERE seq=1",
                              (fixture.canonical(record).decode(),))
        anchor = verify.sha({k: envelope[k] for k in ("schema", "source", "flags", "records")})
        for method in (lambda: self.store.submit(None, expected_proof=anchor),
                       lambda: self.store.revoke(expected_proof=anchor)):
            self.unchanged(method, "inconsistent persisted chain", healthy=False)

    def test_full_validation_precedes_stale_anchor_check(self):
        self.store.submit(fixture.request())
        self.store.db.execute("DELETE FROM requests")
        for method in (lambda: self.store.submit(None, expected_proof="0" * 64),
                       lambda: self.store.revoke(expected_proof="0" * 64)):
            self.unchanged(method, "persisted request mapping mismatch", healthy=False)

    def remove_suffix(self):
        self.store.db.execute("BEGIN IMMEDIATE")
        self.store.db.execute("DELETE FROM records WHERE seq>5")
        self.store.db.execute("DELETE FROM requests WHERE key='second'")
        self.store.db.commit()

    def assert_rollback_guarded(self, anchor):
        self.unchanged(lambda: self.store.submit(
            fixture.request("fresh"), expected_proof=anchor), "expected proof mismatch")
        self.unchanged(lambda: self.store.revoke(expected_proof=anchor),
                       "expected proof mismatch")
        self.checked()

    def test_coherent_group_and_request_row_rollback_rejects_original_anchor(self):
        self.store.submit(fixture.request("first"))
        first = self.envelope()
        self.store.submit(fixture.request("second"))
        anchor = self.proof()
        self.remove_suffix()
        self.assertEqual(self.envelope(), first)
        self.assert_rollback_guarded(anchor)

    def test_coherent_revocation_removal_rejects_original_anchor(self):
        self.store.submit(fixture.request("first"))
        before = self.envelope()
        self.store.revoke()
        anchor = self.proof()
        self.store.db.execute("DELETE FROM records WHERE seq=6")
        self.assertEqual(self.envelope(), before)
        self.assert_rollback_guarded(anchor)

    def test_accepting_attacker_current_digest_does_not_authenticate_history(self):
        self.store.submit(fixture.request("first"))
        self.store.submit(fixture.request("second"))
        original = self.envelope()
        self.remove_suffix()
        self.assert_rollback_guarded(original["proof"]["digest"])
        attacker_digest = self.proof()
        self.store.submit(fixture.request("replacement"), expected_proof=attacker_digest)
        current = self.checked()
        self.assertIs(current["proof"]["authenticity"], False)
        prior = self.work / "original.json"
        prior.write_bytes(fixture.canonical(original))
        with self.assertRaises(ValueError):
            verify.verify(self.work / "envelope.json", previous_envelope=prior,
                          expected_previous_proof=original["proof"]["digest"])

    def test_stale_consumer_explicitly_checks_continuity_before_new_anchor(self):
        self.store.submit(fixture.request("first"))
        previous = self.envelope()
        prior_path = self.work / "prior.json"
        prior_path.write_bytes(fixture.canonical(previous))
        self.store.submit(fixture.request("second"))
        anchor = previous["proof"]["digest"]
        self.unchanged(lambda: self.store.submit(
            fixture.request("third"), expected_proof=anchor), "expected proof mismatch")
        current = self.checked()
        result = verify.verify(
            self.work / "envelope.json", previous_envelope=prior_path,
            expected_previous_proof=anchor, expected_proof=current["proof"]["digest"])
        self.assertEqual(result["continuity"], "EXTENDED")
        self.store.submit(fixture.request("third"), expected_proof=current["proof"]["digest"])
        self.assertEqual(len(self.checked()["records"]), 15)

    def race(self, operations):
        anchor = self.proof()
        context = multiprocessing.get_context("spawn")
        workers = []
        try:
            for index, operation in enumerate(operations):
                parent, child = context.Pipe()
                process = context.Process(
                    target=guarded_worker,
                    args=(str(self.path), anchor, operation, f"worker-{index}", child))
                process.start()
                child.close()
                workers.append((process, parent))
            # Constructors finish before either process can begin its guarded mutation.
            for _, channel in workers:
                self.assertTrue(channel.poll(15), "worker failed to reach barrier")
                self.assertEqual(channel.recv(), ("ready", None))
            for _, channel in workers:
                channel.send("go")
            results = []
            for process, channel in workers:
                self.assertTrue(channel.poll(15), "worker failed to report")
                results.append(channel.recv())
                process.join(15)
                self.assertEqual(process.exitcode, 0)
            self.assertCountEqual(results, [
                ("success", None), ("rejected", "expected proof mismatch")])
        finally:
            for process, channel in workers:
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                channel.close()
        return self.checked(separate=True)

    def test_two_processes_guarded_submit_only_one_group_commits(self):
        envelope = self.race(("submit", "submit"))
        self.assertEqual(len(envelope["records"]), 5)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM requests").fetchone(), (1,))

    def test_two_processes_guarded_submit_revoke_only_one_mutation_commits(self):
        self.store.submit(fixture.request("first"))
        envelope = self.race(("submit", "revoke"))
        self.assertIn(len(envelope["records"]), (6, 10))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM requests").fetchone(),
                         (1 if len(envelope["records"]) == 6 else 2,))
        self.store.revoke()
        self.assertEqual(self.checked()["records"][-1]["kind"], "revocation")


if __name__ == "__main__":
    unittest.main()
