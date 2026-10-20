"""Optional caller request binding, not authentication or official WF mappings."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

import fixture
import verify

HERE = Path(__file__).resolve().parent
SOURCE = "a" * 40


class ReceiptBinding(unittest.TestCase):
    def setUp(self):
        self.work = HERE / ".runtime" / ("binding-" + uuid.uuid4().hex)
        self.work.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.work)
        store = fixture.Store(self.work / "state.sqlite", SOURCE)
        try:
            self.first_receipt = store.submit(fixture.request("first"))
            self.first = store.export()
            self.second_receipt = store.submit(fixture.request("second"))
            self.open = store.export()
            store.revoke()
            self.closed = store.export()
        finally:
            store.close()
        self.path = self.work / "current.json"
        self.prior_path = self.work / "prior.json"
        self.receipt_path = self.work / "receipt.json"
        self.write(self.path, self.closed)
        self.write(self.prior_path, self.first)
        self.write(self.receipt_path, self.first_receipt)

    @staticmethod
    def write(path, value):
        path.write_bytes(fixture.canonical(value))

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.work.iterdir()}

    def options(self, value=None):
        return {"expected_source_commit": SOURCE,
                "expected_proof": (self.closed if value is None else value)["proof"]["digest"],
                "receipt": self.receipt_path, "expected_request_key": "first"}

    def check(self, *, value=None, accepted=True, **overrides):
        before = self.snapshot()
        try:
            options = {**self.options(value), **overrides}
            if accepted:
                return verify.verify(self.path, **options)
            with self.assertRaisesRegex(ValueError, "^invalid synthetic envelope$"):
                verify.verify(self.path, **options)
        finally:
            self.assertEqual(self.snapshot(), before)

    def cli(self, *args, value=None, code=0, receipt=True):
        before = self.snapshot()
        command = [sys.executable, "-I", str(HERE / "verify.py"), str(self.path),
                   "--expected-source-commit", SOURCE, "--expected-proof",
                   self.options(value)["expected_proof"]]
        if receipt:
            command.extend(["--receipt", str(self.receipt_path)])
        result = subprocess.run(command + list(args), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.snapshot(), before)
        if code:
            self.assertEqual(result.stdout, '{"result":"REJECTED"}\n')
        return result.stdout

    def assert_before_io(self, options):
        before = self.snapshot()
        with patch.object(verify.os, "open") as opened:
            with self.assertRaisesRegex(ValueError, "^invalid synthetic envelope$"):
                verify.verify(self.work / "nonexistent-current", **options)
            opened.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_correct_binding_first_and_later_receipts_open_and_closed_api_cli(self):
        for value in (self.open, self.closed):
            self.write(self.path, value)
            for key, receipt, sequence in (("first", self.first_receipt, 5),
                                           ("second", self.second_receipt, 10)):
                with self.subTest(records=len(value["records"]), key=key):
                    self.write(self.receipt_path, receipt)
                    result = self.check(value=value, expected_request_key=key)
                    expected = {
                        "result": "VERIFIED_HISTORICAL_RECEIPT", "request_key": key,
                        "commit_sequence": sequence, **receipt, "authenticity": False,
                        "expected_request_key": key, "request_key_anchor_supplied": True,
                        "request_key_anchor_matched": True}
                    self.assertTrue(verify.identical(result["receipt_verification"], expected))
                    self.assertEqual(self.cli("--expected-request-key", key, value=value),
                                     json.dumps(result, sort_keys=True) + "\n")

    def test_other_valid_receipt_rejects_bound_but_accepts_unbound(self):
        for value in (self.open, self.closed):
            self.write(self.path, value)
            for wanted, other in (("first", self.second_receipt),
                                  ("second", self.first_receipt)):
                with self.subTest(records=len(value["records"]), wanted=wanted):
                    self.write(self.receipt_path, other)
                    self.check(value=value, accepted=False, expected_request_key=wanted)
                    self.cli("--expected-request-key", wanted, value=value, code=1)
                    unbound = self.check(value=value, expected_request_key=verify._UNSET)
                    self.assertNotEqual(unbound["receipt_verification"]["request_key"], wanted)
                    self.assertEqual(self.cli(value=value), json.dumps(unbound, sort_keys=True) + "\n")

    def test_unknown_valid_key_rejects(self):
        self.check(accepted=False, expected_request_key="unknown")
        self.cli("--expected-request-key", "unknown", code=1)

    def test_uncommitted_key_rejects_in_retained_checkpoint(self):
        self.write(self.path, self.first)
        self.check(value=self.first, accepted=False, expected_request_key="second")
        self.cli("--expected-request-key", "second", value=self.first, code=1)
        self.write(self.receipt_path, self.second_receipt)
        self.check(value=self.first, accepted=False, expected_request_key="second")

    def test_strict_key_syntax_and_types_reject_before_any_descriptor_open(self):
        class Text(str):
            pass

        for bad in (None, False, True, 0, 1, [], {}, b"first", Text("first"), "",
                    "a" * 49, "First", "first_key", "first key", " first", "first ",
                    "first\n", "first\r\n", "first\0", "é", "ａ", "a/b"):
            with self.subTest(bad=bad):
                self.assert_before_io({
                    **self.options(), "expected_request_key": bad,
                    "receipt": self.work / "nonexistent-receipt",
                    "previous_envelope": self.work / "nonexistent-prior",
                    "expected_previous_proof": self.first["proof"]["digest"]})

    def test_key_without_receipt_rejects_before_any_descriptor_open(self):
        options = self.options()
        del options["receipt"]
        self.assert_before_io(options)
        self.assert_before_io({**options, "receipt": None})

    def test_missing_one_or_both_current_anchors_rejects_before_io(self):
        for omitted in (("expected_source_commit",), ("expected_proof",),
                        ("expected_source_commit", "expected_proof")):
            with self.subTest(omitted=omitted):
                options = self.options()
                for name in omitted:
                    del options[name]
                self.assert_before_io(options)

    def test_unchanged_and_extended_continuity_preserve_hold_review(self):
        for previous, status, added in ((self.closed, "UNCHANGED", 0),
                                        (self.first, "EXTENDED", 6)):
            with self.subTest(status=status):
                self.write(self.prior_path, previous)
                options = {"previous_envelope": self.prior_path,
                           "expected_previous_proof": previous["proof"]["digest"],
                           "review_summary": True}
                result = self.check(**options)
                self.assertEqual(result["continuity"], status)
                self.assertEqual(result["added_records"], added)
                summary = result["review_summary"]
                self.assertEqual(summary["release_status"], "HOLD")
                self.assertIs(summary["release_authorized"], False)
                self.assertIs(summary["execution"], False)
                self.assertIs(summary["authenticity"], False)
                unbound = self.check(expected_request_key=verify._UNSET, **options)
                self.assertEqual(summary, unbound["review_summary"])
                self.assertEqual(self.cli(
                    "--expected-request-key", "first", "--previous-envelope", str(self.prior_path),
                    "--expected-previous-proof", previous["proof"]["digest"], "--review-summary"),
                    json.dumps(result, sort_keys=True) + "\n")

    def test_default_and_unbound_output_are_exactly_unchanged(self):
        expected = {
            "result": "VERIFIED_SYNTHETIC_ONLY", "records": 11, "source_commit": SOURCE,
            "proof": self.closed["proof"]["digest"], "source_anchor_supplied": False,
            "source_anchor_matched": None, "proof_anchor_supplied": False,
            "proof_anchor_matched": None, "execution": False, "authenticity": False}
        before = self.snapshot()
        self.assertTrue(verify.identical(verify.verify(self.path), expected))
        command = [sys.executable, "-I", str(HERE / "verify.py"), str(self.path)]
        output = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual((output.returncode, output.stderr), (0, ""))
        self.assertEqual(output.stdout, json.dumps(expected, sort_keys=True) + "\n")
        expected.update(source_anchor_supplied=True, source_anchor_matched=True,
                        proof_anchor_supplied=True, proof_anchor_matched=True)
        expected["receipt_verification"] = {
            "result": "VERIFIED_HISTORICAL_RECEIPT", "request_key": "first",
            "commit_sequence": 5, **self.first_receipt, "authenticity": False}
        self.assertTrue(verify.identical(
            self.check(expected_request_key=verify._UNSET), expected))
        self.assertEqual(self.cli(), json.dumps(expected, sort_keys=True) + "\n")
        self.assertEqual(self.snapshot(), before)

    def test_bound_verification_opens_current_prior_receipt_once_each(self):
        before = self.snapshot()
        original_open = verify.os.open
        with patch.object(verify.os, "open", wraps=original_open) as opened:
            result = verify.verify(
                self.path, **self.options(), previous_envelope=self.prior_path,
                expected_previous_proof=self.first["proof"]["digest"], review_summary=True)
        self.assertEqual([call.args[0] for call in opened.call_args_list],
                         [self.path, self.prior_path, self.receipt_path])
        self.assertEqual(result["receipt_verification"]["expected_request_key"], "first")
        self.assertEqual(self.snapshot(), before)

    def test_same_path_continuity_reuses_current_descriptor(self):
        original_open = verify.os.open
        before = self.snapshot()
        with patch.object(verify.os, "open", wraps=original_open) as opened:
            result = verify.verify(
                self.path, **self.options(), previous_envelope=self.path,
                expected_previous_proof=self.closed["proof"]["digest"])
        self.assertEqual([call.args[0] for call in opened.call_args_list],
                         [self.path, self.receipt_path])
        self.assertEqual(result["continuity"], "UNCHANGED")
        self.assertEqual(self.snapshot(), before)

    def test_tampered_receipt_rejects_even_with_matching_expected_key(self):
        for field, bad in (("commit", "0" * 64), ("request_hash", "0" * 64),
                           ("execution", True), ("historical_record_only", False)):
            with self.subTest(field=field):
                self.write(self.receipt_path, {**self.first_receipt, field: bad})
                self.check(accepted=False)
                self.cli("--expected-request-key", "first", code=1)

    def test_boundary_keys_supported_by_producer_api_and_cli(self):
        store = fixture.Store(self.work / "boundary.sqlite", SOURCE)
        try:
            for key in ("-", "a", "a" * 48):
                with self.subTest(key=key):
                    receipt = store.submit(fixture.request(key))
                    value = store.export()
                    self.write(self.path, value)
                    self.write(self.receipt_path, receipt)
                    result = self.check(value=value, expected_request_key=key)
                    self.assertEqual(result["receipt_verification"]["request_key"], key)
                    self.assertEqual(self.cli("--expected-request-key", key, value=value),
                                     json.dumps(result, sort_keys=True) + "\n")
        finally:
            store.close()

    def test_mismatched_source_or_proof_still_rejects(self):
        for name, bad in (("expected_source_commit", "b" * 40),
                          ("expected_proof", "0" * 64)):
            with self.subTest(name=name):
                self.check(accepted=False, **{name: bad})
                self.cli("--expected-request-key", "first",
                         "--" + name.replace("_", "-"), bad, code=1)

    def test_empty_cli_key_is_supplied_and_rejects_cleanly(self):
        self.cli("--expected-request-key", "", code=1)

    def test_cli_key_without_receipt_rejects_before_io_without_traceback(self):
        self.cli("--expected-request-key", "first", receipt=False, code=1)
        with patch.object(sys, "argv", [
                "verify.py", str(self.work / "nonexistent-current"),
                "--expected-request-key", "first", "--expected-source-commit", SOURCE,
                "--expected-proof", self.closed["proof"]["digest"]]), \
                patch.object(verify.os, "open") as opened, patch("builtins.print") as printed:
            with self.assertRaises(SystemExit) as exit_result:
                verify.main()
            self.assertEqual(exit_result.exception.code, 1)
            opened.assert_not_called()
            printed.assert_called_once_with('{"result":"REJECTED"}')


if __name__ == "__main__":
    unittest.main()
