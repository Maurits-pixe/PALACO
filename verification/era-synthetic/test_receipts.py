"""Local historical-receipt regressions, not official WF test mappings."""
import copy
import json
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


class HistoricalReceipts(unittest.TestCase):
    def setUp(self):
        runtime = HERE / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
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
        self.path = self.work / "envelope.json"
        self.receipt_path = self.work / "receipt.json"
        self.prior_path = self.work / "previous.json"
        self.write(self.path, self.closed)
        self.write(self.receipt_path, self.first_receipt)
        self.write(self.prior_path, self.first)

    @staticmethod
    def write(path, value):
        path.write_bytes(fixture.canonical(value))

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.work.iterdir()}

    def options(self, value=None):
        return {"receipt": self.receipt_path, "expected_source_commit": SOURCE,
                "expected_proof": (self.closed if value is None else value)["proof"]["digest"]}

    def check(self, *, accepted=True, value=None, **overrides):
        before = self.snapshot()
        try:
            options = {**self.options(value), **overrides}
            if accepted:
                return verify.verify(self.path, **options)
            with self.assertRaises((ValueError, RecursionError)):
                verify.verify(self.path, **options)
        finally:
            self.assertEqual(self.snapshot(), before)

    def cli(self, *args, code=0, value=None):
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, "-I", str(HERE / "verify.py"), str(self.path),
             "--receipt", str(self.receipt_path), "--expected-source-commit", SOURCE,
             "--expected-proof", self.options(value)["expected_proof"], *args],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.snapshot(), before)
        output = json.loads(result.stdout)
        if code:
            self.assertEqual(output, {"result": "REJECTED"})
        return output

    @staticmethod
    def reseal(value):
        previous = fixture.digest({k: value[k] for k in ("schema", "source", "flags")})
        hashes = {}
        for seq, record in enumerate(value["records"], 1):
            old = record["hash"]
            for key in ("identity", "evidence", "decision", "authorization"):
                reference = record["data"].get(key)
                if type(reference) is str and reference in hashes:
                    record["data"][key] = hashes[reference]
            record["seq"], record["prev"] = seq, previous
            record["hash"] = fixture.digest(
                {k: record[k] for k in ("seq", "kind", "data", "prev")})
            hashes[old] = previous = record["hash"]
        value["proof"]["digest"] = fixture.digest(
            {k: value[k] for k in ("schema", "source", "flags", "records")})
        return value

    def test_real_receipts_open_later_and_revoked_exact_api_and_cli(self):
        for value, receipts in ((self.first, (self.first_receipt,)),
                                (self.open, (self.first_receipt, self.second_receipt)),
                                (self.closed, (self.first_receipt, self.second_receipt))):
            for receipt in receipts:
                with self.subTest(records=len(value["records"]), receipt=receipt):
                    self.write(self.path, value)
                    self.write(self.receipt_path, receipt)
                    result = self.check(value=value)
                    record = next(r for r in value["records"] if r["hash"] == receipt["commit"])
                    expected = {
                        "result": "VERIFIED_HISTORICAL_RECEIPT",
                        "request_key": record["data"]["request"]["request_key"],
                        "commit_sequence": record["seq"], **receipt, "authenticity": False}
                    self.assertTrue(verify.identical(result["receipt_verification"], expected))
                    plain = verify.verify(self.path, expected_source_commit=SOURCE,
                                          expected_proof=value["proof"]["digest"])
                    self.assertEqual({k: v for k, v in result.items()
                                      if k != "receipt_verification"}, plain)
                    self.assertEqual(result["result"], "VERIFIED_SYNTHETIC_ONLY")
                    self.assertEqual(self.cli(value=value), result)

    def test_default_output_exactly_unchanged(self):
        expected = {
            "result": "VERIFIED_SYNTHETIC_ONLY", "records": 11, "source_commit": SOURCE,
            "proof": self.closed["proof"]["digest"], "source_anchor_supplied": False,
            "source_anchor_matched": None, "proof_anchor_supplied": False,
            "proof_anchor_matched": None, "execution": False, "authenticity": False}
        self.assertTrue(verify.identical(verify.verify(self.path), expected))
        result = subprocess.run(
            [sys.executable, "-I", str(HERE / "verify.py"), str(self.path)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, json.dumps(expected, sort_keys=True) + "\n")

    def test_missing_anchors_reject_before_reads_api_and_cli(self):
        for names in ((), ("expected_source_commit",), ("expected_proof",)):
            options = self.options()
            for name in ("expected_source_commit", "expected_proof"):
                if name not in names:
                    del options[name]
            with self.subTest(names=names), patch.object(Path, "open") as opened:
                with self.assertRaises(ValueError):
                    verify.verify(self.path, **options)
                opened.assert_not_called()
            args = [sys.executable, "-I", str(HERE / "verify.py"), str(self.path),
                    "--receipt", str(self.receipt_path)]
            for name in names:
                args.extend(["--" + name.replace("_", "-"), options[name]])
            result = subprocess.run(args, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '{"result":"REJECTED"}\n')
            self.assertEqual(result.stderr, "")

    def test_malformed_anchors_reject_before_reads(self):
        class Text(str):
            pass

        for name, length in (("expected_source_commit", 40), ("expected_proof", 64)):
            for bad in (None, True, 0, [], {}, b"a" * length, Text("a" * length),
                        "", "a" * (length - 1), "a" * (length + 1), "A" * length,
                        "g" * length, "a" * length + "\n"):
                with self.subTest(name=name, bad=bad), patch.object(Path, "open") as opened:
                    with self.assertRaises(ValueError):
                        verify.verify(self.path, **{**self.options(), name: bad})
                    opened.assert_not_called()
            for bad in ("", "A" * length, "g" * length, "a" * (length - 1)):
                self.cli("--" + name.replace("_", "-"), bad, code=1)

    def test_mismatched_anchors_reject_before_receipt_load(self):
        for name, bad in (("expected_source_commit", "b" * 40),
                          ("expected_proof", "0" * 64)):
            with self.subTest(name=name), patch.object(
                    verify, "_load_envelope", wraps=verify._load_envelope) as load:
                self.check(accepted=False, **{name: bad})
                self.assertEqual(load.call_count, 1)
            self.cli("--" + name.replace("_", "-"), bad, code=1)

    def test_invalid_receipt_path_types_reject_before_reads(self):
        for bad in (None, True, 0, [], {}, (self.receipt_path, self.path)):
            with self.subTest(bad=bad), patch.object(Path, "open") as opened:
                with self.assertRaises(ValueError):
                    verify.verify(self.path, **{**self.options(), "receipt": bad})
                opened.assert_not_called()

    def test_receipt_exact_keys_and_container_types(self):
        values = [None, [], [self.first_receipt], True, 0, "receipt",
                  {**self.first_receipt, "authority": "synthetic-recorder"},
                  {**self.first_receipt, "request_key": "first"},
                  {**self.first_receipt, "authenticity": False}]
        values.extend({k: v for k, v in self.first_receipt.items() if k != missing}
                      for missing in self.first_receipt)
        for value in values:
            with self.subTest(value=value):
                self.write(self.receipt_path, value)
                self.check(accepted=False)
                self.cli(code=1)

    def test_receipt_flags_strict_booleans(self):
        for key, bad_values in (
                ("historical_record_only", (False, 0, 1, None, "true", [], {})),
                ("execution", (True, 0, 1, None, "false", [], {}))):
            for bad in bad_values:
                with self.subTest(key=key, bad=bad):
                    self.write(self.receipt_path, {**self.first_receipt, key: bad})
                    self.check(accepted=False)
                    self.cli(code=1)

    def test_receipt_hash_types_lengths_and_unrelated_swaps(self):
        for key in ("commit", "request_hash"):
            for bad in (None, True, 0, 1, [], {}, "", "a" * 63, "a" * 65,
                        "A" * 64, "g" * 64, "a" * 64 + "\n", "0" * 64,
                        self.second_receipt[key],
                        self.first_receipt["request_hash" if key == "commit" else "commit"],
                        self.closed["records"][3]["hash"]):
                with self.subTest(key=key, bad=bad):
                    self.write(self.receipt_path, {**self.first_receipt, key: bad})
                    self.check(accepted=False)
                    self.cli(code=1)

    def test_strict_bounded_receipt_json_api_and_clean_cli(self):
        encoded = fixture.canonical(self.first_receipt)
        payloads = [
            b"", b"{", b"\xff", encoded + b"{}",
            b'{"commit":"x","commit":"y"}',
            b'{"nested":{"x":1,"x":2}}',
            b'{"commit":NaN}', b'{"commit":Infinity}', b'{"commit":-Infinity}',
            b"[" * 1500 + b"0" + b"]" * 1500,
            encoded + b" " * (4097 - len(encoded)),
        ]
        for payload in payloads:
            with self.subTest(payload=payload[:60]):
                self.receipt_path.write_bytes(payload)
                self.check(accepted=False)
                self.cli(code=1)
        self.receipt_path.write_bytes(encoded + b" " * (4096 - len(encoded)))
        self.check()
        self.cli()

    def test_same_file_as_envelope_receipt_rejects(self):
        self.check(accepted=False, receipt=self.path)
        self.cli("--receipt", str(self.path), code=1)

    def test_missing_receipt_clean_cli(self):
        self.cli("--receipt", str(self.work / "missing.json"), code=1)

    def test_truncation_requires_deliberately_changed_current_proof(self):
        self.write(self.path, self.first)
        self.check(accepted=False)
        self.cli(code=1)
        self.check(value=self.first)
        self.cli(value=self.first)

    def test_forged_rehashed_decision_and_authority_reject_matching_receipt(self):
        for index, key, bad in ((2, "decision", "EXECUTE"),
                                (3, "authority", "real-authority"),
                                (4, "request", {**fixture.request("first"),
                                                "authority": "real-authority"})):
            with self.subTest(index=index):
                value = copy.deepcopy(self.closed)
                value["records"][index]["data"][key] = bad
                self.reseal(value)
                record = value["records"][4]
                forged = {**self.first_receipt, "commit": record["hash"],
                          "request_hash": record["data"]["request_hash"]}
                self.write(self.path, value)
                self.write(self.receipt_path, forged)
                self.check(accepted=False, value=value)
                self.cli(code=1, value=value)

    def test_later_invalid_records_never_bypassed_by_old_receipt(self):
        value = copy.deepcopy(self.closed)
        value["records"][-1]["data"]["execution"] = True
        self.reseal(value)
        self.write(self.path, value)
        self.check(accepted=False, value=value)
        self.cli(code=1, value=value)

    def test_continuity_extension_and_unchanged_preserved(self):
        for prior in (self.first, self.closed):
            with self.subTest(records=len(prior["records"])):
                self.write(self.prior_path, prior)
                options = {"previous_envelope": self.prior_path,
                           "expected_previous_proof": prior["proof"]["digest"]}
                result = self.check(**options)
                self.assertEqual(result["continuity"],
                                 "UNCHANGED" if prior == self.closed else "EXTENDED")
                self.assertEqual(result, self.cli(
                    "--previous-envelope", str(self.prior_path),
                    "--expected-previous-proof", prior["proof"]["digest"]))

    def test_continuity_rollback_and_fork_reject_despite_receipt_match(self):
        fork_store = fixture.Store(self.work / "fork.sqlite", SOURCE)
        try:
            fork_store.submit(fixture.request("first"))
            fork_store.submit(fixture.request("other"))
            fork = fork_store.export()
        finally:
            fork_store.close()
        for current, prior in ((self.first, self.closed), (self.open, fork)):
            with self.subTest(records=len(current["records"])):
                self.write(self.path, current)
                self.write(self.prior_path, prior)
                self.check(value=current)
                self.check(accepted=False, value=current, previous_envelope=self.prior_path,
                           expected_previous_proof=prior["proof"]["digest"])
                self.cli("--previous-envelope", str(self.prior_path),
                         "--expected-previous-proof", prior["proof"]["digest"],
                         value=current, code=1)

    def test_continuity_pair_and_previous_anchor_still_required(self):
        for options in ({"previous_envelope": self.prior_path},
                        {"expected_previous_proof": self.first["proof"]["digest"]},
                        {"previous_envelope": None,
                         "expected_previous_proof": self.first["proof"]["digest"]},
                        {"previous_envelope": self.prior_path,
                         "expected_previous_proof": None}):
            with self.subTest(options=options), patch.object(Path, "open") as opened:
                with self.assertRaises(ValueError):
                    verify.verify(self.path, **{**self.options(), **options})
                opened.assert_not_called()
        self.check(accepted=False, previous_envelope=self.prior_path,
                   expected_previous_proof="0" * 64)
        self.cli("--previous-envelope", str(self.prior_path),
                 "--expected-previous-proof", "0" * 64, code=1)

    def test_review_summary_independent_terminal_requirement(self):
        for value in (self.first, self.open):
            self.write(self.path, value)
            self.check(value=value)
            self.check(accepted=False, value=value, review_summary=True)
            self.cli("--review-summary", value=value, code=1)
        self.write(self.path, self.closed)
        result = self.check(review_summary=True, previous_envelope=self.prior_path,
                            expected_previous_proof=self.first["proof"]["digest"])
        self.assertEqual(result["review_summary"]["committed_requests"], 2)
        self.assertEqual(result["review_summary"]["revocation_sequence"], 11)
        self.assertEqual(result["review_summary"]["release_status"], "HOLD")
        self.assertEqual(result, self.cli(
            "--review-summary", "--previous-envelope", str(self.prior_path),
            "--expected-previous-proof", self.first["proof"]["digest"]))

    def test_each_envelope_and_receipt_opened_only_once(self):
        original = verify.os.open
        opened = []

        def tracked(path, *args, **kwargs):
            opened.append(path)
            return original(path, *args, **kwargs)

        for prior in (self.prior_path, self.path):
            with self.subTest(prior=prior):
                opened.clear()
                digest = (self.first if prior == self.prior_path else self.closed)["proof"]["digest"]
                with patch.object(verify.os, "open", tracked):
                    verify.verify(self.path, **self.options(), review_summary=True,
                                  previous_envelope=prior, expected_previous_proof=digest)
                self.assertEqual(opened.count(self.path), 1)
                self.assertEqual(opened.count(self.receipt_path), 1)
                if prior != self.path:
                    self.assertEqual(opened.count(prior), 1)
                self.assertEqual(len(opened), 3 if prior != self.path else 2)

    def test_receipt_loader_reads_at_most_bound_plus_one(self):
        original = verify.os.fdopen
        reads = []

        class Bounded:
            def __init__(inner, fd, *args, **kwargs):
                inner.stream = original(fd, *args, **kwargs)

            def __enter__(inner):
                return inner

            def __exit__(inner, *args):
                inner.stream.close()

            def read(inner, size):
                reads.append(size)
                return inner.stream.read(size)

        def tracked(fd, *args, **kwargs):
            if verify.os.fstat(fd).st_ino == self.receipt_path.stat().st_ino:
                return Bounded(fd, *args, **kwargs)
            return original(fd, *args, **kwargs)

        with patch.object(verify.os, "fdopen", tracked):
            verify.verify(self.path, **self.options())
        self.assertEqual(reads, [4097])


if __name__ == "__main__":
    unittest.main()
