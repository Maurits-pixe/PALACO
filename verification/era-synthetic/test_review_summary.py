"""Local advisory-summary regressions, not official WF test mappings."""
import ast
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


class ReviewSummary(unittest.TestCase):
    def setUp(self):
        work = HERE / ".runtime"
        work.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        store = fixture.Store(self.work / "state.sqlite", SOURCE)
        try:
            store.submit(fixture.request("first"))
            self.previous = store.export()
            store.submit(fixture.request("second"))
            self.open = store.export()
            store.revoke()
            self.closed = store.export()
        finally:
            store.close()
        self.path = self.work / "current.json"
        self.prior_path = self.work / "previous.json"
        self.write(self.path, self.closed)
        self.write(self.prior_path, self.previous)

    def write(self, path, value):
        path.write_bytes(fixture.canonical(value))

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.work.iterdir()}

    def options(self, value=None):
        return {"review_summary": True, "expected_source_commit": SOURCE,
                "expected_proof": (self.closed if value is None else value)["proof"]["digest"]}

    def check(self, *, accepted=True, value=None, **overrides):
        before = self.snapshot()
        try:
            options = {**self.options(value), **overrides}
            if accepted:
                return verify.verify(self.path, **options)
            with self.assertRaises(ValueError):
                verify.verify(self.path, **options)
        finally:
            self.assertEqual(self.snapshot(), before)

    def cli(self, *args, code=0):
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, "-I", str(HERE / "verify.py"), str(self.path), *args],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before)
        if code == 2:
            return
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        if code:
            self.assertEqual(output, {"result": "REJECTED"})
        return output, result.stdout

    def cli_args(self, value=None):
        return ["--review-summary", "--expected-source-commit", SOURCE,
                "--expected-proof", self.options(value)["expected_proof"]]

    @staticmethod
    def reseal(value):
        previous = fixture.digest({k: value[k] for k in ("schema", "source", "flags")})
        hashes = {}
        for seq, record in enumerate(value["records"], 1):
            old_hash = record["hash"]
            for key in ("identity", "evidence", "decision", "authorization"):
                reference = record["data"].get(key)
                if type(reference) is str and reference in hashes:
                    record["data"][key] = hashes[reference]
            record["seq"], record["prev"] = seq, previous
            record["hash"] = fixture.digest(
                {k: record[k] for k in ("seq", "kind", "data", "prev")})
            hashes[old_hash] = previous = record["hash"]
        value["proof"]["digest"] = fixture.digest(
            {k: value[k] for k in ("schema", "source", "flags", "records")})
        return value

    def test_exact_summary_api_and_isolated_cli(self):
        result = self.check()
        expected = {
            "schema": "ERA_SYNTHETIC_REVIEW_V1", "source_commit": SOURCE,
            "proof": self.closed["proof"]["digest"], "committed_requests": 2,
            "records": 11, "revocation_sequence": 11, "synthetic_only": True,
            "execution": False, "authenticity": False, "release_authorized": False,
            "release_status": "HOLD", "decision_boundary": "ADVISORY — HUMAN DECISION REQUIRED",
            "open_gates": ["canonical_contract_conformance", "independent_external_verification",
                           "operational_authorization", "human_release_decision"],
        }
        self.assertTrue(verify.identical(result["review_summary"], expected))
        plain = verify.verify(self.path, expected_source_commit=SOURCE,
                              expected_proof=self.closed["proof"]["digest"])
        self.assertEqual({k: v for k, v in result.items() if k != "review_summary"}, plain)
        self.assertEqual(self.cli(*self.cli_args())[0], result)

    def test_default_and_explicit_false_preserve_exact_output(self):
        expected = {
            "result": "VERIFIED_SYNTHETIC_ONLY", "records": 11, "source_commit": SOURCE,
            "proof": self.closed["proof"]["digest"], "source_anchor_supplied": False,
            "source_anchor_matched": None, "proof_anchor_supplied": False,
            "proof_anchor_matched": None, "execution": False, "authenticity": False,
        }
        self.assertTrue(verify.identical(verify.verify(self.path), expected))
        self.assertTrue(verify.identical(verify.verify(self.path, review_summary=False), expected))
        output, raw = self.cli()
        self.assertEqual(output, expected)
        self.assertEqual(raw, json.dumps(expected, sort_keys=True) + "\n")

    def test_strict_boolean_rejects_before_read(self):
        class Number(int):
            pass

        class Text(str):
            pass

        for value in (None, 0, 1, [], {}, "True", Number(1), Text("True")):
            with self.subTest(value=value), patch.object(Path, "open") as opened:
                with self.assertRaises(ValueError):
                    verify.verify(self.path, **{**self.options(), "review_summary": value})
                opened.assert_not_called()

    def test_missing_anchors_reject_before_read(self):
        for names in ((), ("expected_source_commit",), ("expected_proof",)):
            options = self.options()
            for name in ("expected_source_commit", "expected_proof"):
                if name not in names:
                    del options[name]
            with self.subTest(names=names), patch.object(Path, "open") as opened:
                with self.assertRaises(ValueError):
                    verify.verify(self.path, **options)
                opened.assert_not_called()
        self.cli("--review-summary", code=1)
        self.cli("--review-summary", "--expected-source-commit", SOURCE, code=1)
        self.cli("--review-summary", "--expected-proof", self.closed["proof"]["digest"], code=1)

    def test_malformed_anchors_reject_before_read(self):
        class Text(str):
            pass

        for name, length in (("expected_source_commit", 40), ("expected_proof", 64)):
            for value in (None, True, 0, [], {}, b"a" * length, Text("a" * length),
                          "", "a" * (length - 1), "a" * (length + 1), "A" * length,
                          "g" * length, "a" * length + "\n"):
                with self.subTest(name=name, value=value), patch.object(Path, "open") as opened:
                    with self.assertRaises(ValueError):
                        verify.verify(self.path, **{**self.options(), name: value})
                    opened.assert_not_called()
            for value in ("", "A" * length, "g" * length, "a" * (length - 1)):
                self.cli(*self.cli_args(), "--" + name.replace("_", "-"), value, code=1)

    def test_mismatched_anchors_reject(self):
        for name, value in (("expected_source_commit", "b" * 40),
                            ("expected_proof", "0" * 64)):
            with self.subTest(name=name):
                self.check(accepted=False, **{name: value})
                self.cli(*self.cli_args(), "--" + name.replace("_", "-"), value, code=1)

    def test_cli_argument_errors(self):
        for args in (("--review-summary=true",), ("--review-summary", "true"),
                     ("--review-summary", "--expected-proof"),
                     ("--review-summary", "--expected-source-commit")):
            self.cli(*args, code=2)

    def test_one_committed_group(self):
        value = copy.deepcopy(self.closed)
        value["records"] = value["records"][:5] + value["records"][-1:]
        self.write(self.path, self.reseal(value))
        summary = self.check(value=value)["review_summary"]
        self.assertIs(type(summary["committed_requests"]), int)
        self.assertEqual(summary["committed_requests"], 1)
        self.assertEqual(summary["records"], 6)
        self.assertEqual(summary["revocation_sequence"], 6)

    def test_open_prefix_and_rehashed_revocation_removal_reject_only_summary(self):
        removed = copy.deepcopy(self.closed)
        removed["records"].pop()
        self.reseal(removed)
        self.assertEqual(removed, self.open)
        for value in (self.previous, self.open, removed):
            with self.subTest(records=len(value["records"])):
                self.write(self.path, value)
                self.assertEqual(verify.verify(self.path)["records"], len(value["records"]))
                self.check(accepted=False, value=value)
                self.cli(*self.cli_args(value), code=1)

    def test_empty_and_revoked_only_reject_full_checker(self):
        for records in ([], [copy.deepcopy(self.closed["records"][-1])]):
            value = copy.deepcopy(self.closed)
            value["records"] = records
            self.write(self.path, self.reseal(value))
            with self.assertRaises(ValueError):
                verify.verify(self.path)
            self.check(accepted=False, value=value)
            self.cli(*self.cli_args(value), code=1)

    def test_resealed_bad_evidence_authority_decision_and_flags_reject(self):
        for target, key, replacement in (
                (1, "evidence", "wrong"), (2, "decision", "EXECUTE"),
                (3, "authority", "human"), (3, "execution", True),
                (-1, "authority", "human"), (-1, "execution", True),
                ("flags", "synthetic_only", False), ("flags", "synthetic_only", 1),
                ("flags", "execution", True), ("flags", "execution", 0),
                ("flags", "release", True)):
            with self.subTest(target=target, key=key, replacement=replacement):
                value = copy.deepcopy(self.closed)
                data = value["flags"] if target == "flags" else value["records"][target]["data"]
                data[key] = replacement
                self.write(self.path, self.reseal(value))
                with self.assertRaises(ValueError):
                    verify.verify(self.path)
                self.check(accepted=False, value=value)
                self.cli(*self.cli_args(value), code=1)

    def test_self_reported_summary_input_rejects(self):
        value = copy.deepcopy(self.closed)
        value["review_summary"] = self.check()["review_summary"]
        self.write(self.path, value)
        self.check(accepted=False)
        self.cli(*self.cli_args(), code=1)

    def test_continuity_from_open_prior_and_unchanged_revoked(self):
        for previous, added in ((self.previous, 6), (self.open, 1), (self.closed, 0)):
            with self.subTest(added=added):
                self.write(self.prior_path, previous)
                options = {"previous_envelope": self.prior_path,
                           "expected_previous_proof": previous["proof"]["digest"]}
                result = self.check(**options)
                self.assertEqual(result["added_records"], added)
                self.assertEqual(result["previous_records"], len(previous["records"]))
                self.assertEqual(result["continuity"], "EXTENDED" if added else "UNCHANGED")
                self.assertEqual(result["review_summary"]["records"], 11)
                self.assertEqual(self.cli(
                    *self.cli_args(), "--previous-envelope", str(self.prior_path),
                    "--expected-previous-proof", previous["proof"]["digest"])[0], result)

    def test_continuity_rejects_fork_and_revoked_rollback(self):
        shorter = copy.deepcopy(self.closed)
        shorter["records"] = shorter["records"][:5] + shorter["records"][-1:]
        self.reseal(shorter)
        fork = copy.deepcopy(self.closed)
        fork["records"][0]["data"]["request_key"] = "fork"
        request = fork["records"][4]["data"]["request"]
        request["request_key"] = "fork"
        fork["records"][4]["data"]["request_hash"] = fixture.digest(request)
        self.reseal(fork)
        for value in (shorter, fork):
            self.write(self.path, value)
            self.write(self.prior_path, self.closed)
            self.assertIn("review_summary", self.check(value=value))
            self.check(accepted=False, value=value, previous_envelope=self.prior_path,
                       expected_previous_proof=self.closed["proof"]["digest"])
            self.cli(*self.cli_args(value), "--previous-envelope", str(self.prior_path),
                     "--expected-previous-proof", self.closed["proof"]["digest"], code=1)

    def test_continuity_full_prior_validation_and_anchor_still_required(self):
        bad = copy.deepcopy(self.previous)
        bad["records"][1]["data"]["evidence"] = "wrong"
        self.write(self.prior_path, self.reseal(bad))
        self.check(accepted=False, previous_envelope=self.prior_path,
                   expected_previous_proof=bad["proof"]["digest"])
        self.cli(*self.cli_args(), "--previous-envelope", str(self.prior_path),
                 "--expected-previous-proof", bad["proof"]["digest"], code=1)
        self.write(self.prior_path, self.previous)
        for options in ({"previous_envelope": self.prior_path},
                        {"expected_previous_proof": self.previous["proof"]["digest"]},
                        {"previous_envelope": self.prior_path, "expected_previous_proof": None},
                        {"previous_envelope": self.prior_path, "expected_previous_proof": "0" * 64}):
            self.check(accepted=False, **options)

    def test_same_loaded_object_single_read_and_readonly(self):
        original = Path.open
        opened = []

        def monitor(path, *args, **kwargs):
            opened.append((path, args))
            return original(path, *args, **kwargs)

        before = self.snapshot()
        with patch.object(Path, "open", monitor), patch.object(
                verify, "_verify_envelope", wraps=verify._verify_envelope) as validate:
            result = verify.verify(self.path, **self.options())
            self.assertEqual(result["review_summary"]["records"], 11)
            self.assertEqual(validate.call_count, 1)
        self.assertEqual(opened, [(self.path, ("rb",))])
        self.assertEqual(self.snapshot(), before)
        opened.clear()
        with patch.object(Path, "open", monitor):
            verify.verify(self.path, **self.options(), previous_envelope=self.prior_path,
                          expected_previous_proof=self.previous["proof"]["digest"])
        self.assertCountEqual(opened, [(self.path, ("rb",)), (self.prior_path, ("rb",))])
        self.assertEqual(self.snapshot(), before)

    def test_verifier_does_not_import_fixture_or_sqlite(self):
        tree = ast.parse((HERE / "verify.py").read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append((node.module or "").split(".")[0])
        self.assertNotIn("fixture", imports)
        self.assertNotIn("sqlite3", imports)


if __name__ == "__main__":
    unittest.main()
