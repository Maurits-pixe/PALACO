"""Offline continuity regressions, not official contract scenarios."""
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
ROOT = HERE.parents[1]
SOURCE = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
OTHER_SOURCE = "1" * 40 if SOURCE != "1" * 40 else "2" * 40


class Continuity(unittest.TestCase):
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
            self.current = store.export()
            store.revoke()
            self.revoked = store.export()
        finally:
            store.close()
        self.prior_path = self.work / "previous.json"
        self.path = self.work / "current.json"
        self.write(self.prior_path, self.previous)
        self.write(self.path, self.current)
        self.anchor = self.previous["proof"]["digest"]

    def write(self, path, value):
        path.write_bytes(fixture.canonical(value))

    def snapshot(self):
        return {p: p.read_bytes() for p in self.work.glob("*.json")}

    def check(self, *, accepted=True, current=None, **overrides):
        options = {"previous_envelope": self.prior_path,
                   "expected_previous_proof": self.anchor, **overrides}
        before = self.snapshot()
        try:
            if accepted:
                return verify.verify(current or self.path, **options)
            with self.assertRaises((ValueError, OSError)):
                verify.verify(current or self.path, **options)
        finally:
            self.assertEqual(self.snapshot(), before)

    def cli(self, *args, accepted=True, code=None):
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, "-I", str(HERE / "verify.py"), str(self.path), *args],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, code if code is not None else 0 if accepted else 1,
                         result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before)
        if code == 2:
            return
        output = json.loads(result.stdout)
        self.assertEqual(output["result"], "VERIFIED_SYNTHETIC_ONLY" if accepted else "REJECTED")
        return output

    def paired_cli(self, *, accepted=True, **anchors):
        args = ["--previous-envelope", str(self.prior_path),
                "--expected-previous-proof", self.anchor]
        for name, value in anchors.items():
            args += ["--" + name.replace("_", "-"), value]
        return self.cli(*args, accepted=accepted)

    @staticmethod
    def reseal(envelope):
        previous = fixture.digest({k: envelope[k] for k in ("schema", "source", "flags")})
        hashes = {}
        for index, record in enumerate(envelope["records"], 1):
            old_hash = record["hash"]
            for key in ("identity", "evidence", "decision", "authorization"):
                reference = record["data"].get(key)
                if type(reference) is str and reference in hashes:
                    record["data"][key] = hashes[reference]
            record["seq"], record["prev"] = index, previous
            record["hash"] = fixture.digest(
                {k: record[k] for k in ("seq", "kind", "data", "prev")})
            hashes[old_hash] = previous = record["hash"]
        envelope["proof"]["digest"] = fixture.digest(
            {k: envelope[k] for k in ("schema", "source", "flags", "records")})
        return envelope

    def assert_output(self, output, previous, added):
        self.assertEqual(output["previous_records"], previous)
        self.assertEqual(output["added_records"], added)
        self.assertEqual(output["records"], previous + added)
        self.assertEqual(output["previous_proof"], self.anchor)
        self.assertEqual(output["continuity"], "EXTENDED" if added else "UNCHANGED")
        self.assertIs(output["previous_proof_anchor_matched"], True)
        self.assertIs(output["execution"], False)
        self.assertIs(output["authenticity"], False)
        self.assertEqual(output["result"], "VERIFIED_SYNTHETIC_ONLY")

    def test_extension_and_current_anchors(self):
        for source, proof in ((False, False), (True, False), (False, True), (True, True)):
            anchors = {}
            if source:
                anchors["expected_source_commit"] = SOURCE
            if proof:
                anchors["expected_proof"] = self.current["proof"]["digest"]
            with self.subTest(source=source, proof=proof):
                result = self.check(**anchors)
                self.assert_output(result, 5, 5)
                self.assertEqual(result, self.paired_cli(**anchors))

    def test_unchanged_and_formatting(self):
        self.path.write_text(json.dumps(self.previous, indent=2), encoding="utf-8")
        self.assertNotEqual(self.path.read_bytes(), self.prior_path.read_bytes())
        self.assert_output(self.check(), 5, 0)
        self.assert_output(self.paired_cli(), 5, 0)

    def test_same_file_unchanged(self):
        self.assert_output(self.check(current=self.prior_path), 5, 0)
        self.write(self.path, self.previous)
        self.assert_output(self.cli("--previous-envelope", str(self.path),
                                    "--expected-previous-proof", self.anchor), 5, 0)

    def test_revocation_extension(self):
        self.write(self.prior_path, self.current)
        self.anchor = self.current["proof"]["digest"]
        self.write(self.path, self.revoked)
        self.assert_output(self.check(), 10, 1)
        self.assert_output(self.paired_cli(), 10, 1)

    def test_revoked_unchanged(self):
        self.write(self.prior_path, self.revoked)
        self.write(self.path, self.revoked)
        self.anchor = self.revoked["proof"]["digest"]
        self.assert_output(self.check(), 11, 0)
        self.assert_output(self.paired_cli(), 11, 0)

    def test_api_pairing_and_none_rejected(self):
        for options in (
                {"previous_envelope": self.prior_path},
                {"expected_previous_proof": self.anchor},
                {"previous_envelope": None, "expected_previous_proof": self.anchor},
                {"previous_envelope": self.prior_path, "expected_previous_proof": None},
                {"previous_envelope": None, "expected_previous_proof": None}):
            with self.subTest(options=options):
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    verify.verify(self.path, **options)
                self.assertEqual(self.snapshot(), before)

    def test_api_previous_anchor_strict(self):
        class Text(str):
            pass

        for anchor in ("", "a" * 63, "a" * 65, "A" * 64, "g" * 64,
                       "a" * 64 + "\n", " " + "a" * 64, None, 0, True, [], {},
                       b"a" * 64, Text(self.anchor), "0" * 64):
            with self.subTest(anchor=anchor):
                self.check(expected_previous_proof=anchor, accepted=False)

    def test_cli_pairing_and_digest_rejected(self):
        self.cli("--previous-envelope", str(self.prior_path), accepted=False)
        self.cli("--expected-previous-proof", self.anchor, accepted=False)
        for anchor in ("", "A" * 64, "a" * 63, "a" * 65, "g" * 64,
                       "a" * 64 + "\n", "0" * 64):
            self.cli("--previous-envelope", str(self.prior_path),
                     "--expected-previous-proof", anchor, accepted=False)
        for option in ("--previous-envelope", "--expected-previous-proof"):
            self.cli(option, code=2)

    def test_current_anchors_still_reject_mismatch(self):
        for anchors in ({"expected_source_commit": OTHER_SOURCE},
                        {"expected_proof": "0" * 64}):
            self.check(accepted=False, **anchors)
            self.paired_cli(accepted=False, **anchors)

    def test_fully_rehashed_source_divergence(self):
        changed = copy.deepcopy(self.current)
        changed["source"]["commit"] = OTHER_SOURCE
        self.write(self.path, self.reseal(changed))
        self.assertEqual(verify.verify(self.path)["source_commit"], OTHER_SOURCE)
        self.check(accepted=False, expected_source_commit=OTHER_SOURCE,
                   expected_proof=changed["proof"]["digest"])
        self.paired_cli(accepted=False)

    def test_valid_same_source_divergent_branch(self):
        changed = copy.deepcopy(self.current)
        changed["records"][0]["data"]["request_key"] = "fork"
        request = changed["records"][4]["data"]["request"]
        request["request_key"] = "fork"
        changed["records"][4]["data"]["request_hash"] = fixture.digest(request)
        self.write(self.path, self.reseal(changed))
        self.assertEqual(verify.verify(self.path)["records"], 10)
        self.check(accepted=False)
        self.paired_cli(accepted=False)

    def test_prior_tamper_resealed_or_truncated_rejected(self):
        for mutation in ("tamper", "resealed", "truncated"):
            with self.subTest(mutation=mutation):
                prior = copy.deepcopy(self.current)
                if mutation == "truncated":
                    prior["records"] = prior["records"][:5]
                else:
                    prior["source"]["commit"] = OTHER_SOURCE
                if mutation != "tamper":
                    self.reseal(prior)
                self.write(self.prior_path, prior)
                self.write(self.path, self.revoked)
                self.anchor = self.current["proof"]["digest"]
                if mutation != "tamper":
                    verify.verify(self.prior_path)
                self.check(accepted=False)
                self.paired_cli(accepted=False)

    def test_current_rollback_rejected(self):
        self.write(self.prior_path, self.current)
        self.anchor = self.current["proof"]["digest"]
        self.write(self.path, self.previous)
        verify.verify(self.path)
        self.check(accepted=False)
        self.paired_cli(accepted=False)

    def test_malformed_prior_inputs(self):
        raw = fixture.canonical(self.previous)
        for content in (b"{", b"\xff", b" " * (verify.LIMIT + 1),
                        raw.replace(b'"schema":', b'"schema":0,"schema":', 1),
                        raw.replace(b'"seq":1', b'"seq":NaN', 1),
                        raw.replace(b'"seq":1', b'"seq":Infinity', 1)):
            with self.subTest(content=content[:50]):
                self.prior_path.write_bytes(content)
                self.check(accepted=False)
                self.paired_cli(accepted=False)

    def test_missing_prior(self):
        self.prior_path.unlink()
        self.check(accepted=False)
        self.paired_cli(accepted=False)

    def test_matching_anchors_never_bypass_full_validation(self):
        for target in (self.path, self.prior_path):
            for mutation in ("decision", "execution", "seq"):
                with self.subTest(target=target, mutation=mutation):
                    self.write(self.path, self.current)
                    self.write(self.prior_path, self.previous)
                    bad = copy.deepcopy(self.current if target == self.path else self.previous)
                    if mutation == "decision":
                        bad["records"][2]["data"]["decision"] = "EXECUTE"
                    elif mutation == "execution":
                        bad["flags"]["execution"] = 0
                    else:
                        bad["records"][0]["seq"] = True
                    if mutation != "seq":
                        self.reseal(bad)
                    else:
                        bad["proof"]["digest"] = fixture.digest(
                            {k: bad[k] for k in ("schema", "source", "flags", "records")})
                    self.write(target, bad)
                    self.anchor = (bad if target == self.prior_path else self.previous)["proof"]["digest"]
                    proof = (bad if target == self.path else self.current)["proof"]["digest"]
                    self.check(accepted=False, expected_source_commit=SOURCE, expected_proof=proof)
                    self.paired_cli(accepted=False, expected_source_commit=SOURCE, expected_proof=proof)

    def test_empty_and_revoked_only_prior_rejected(self):
        for records in ([], [copy.deepcopy(self.revoked["records"][-1])]):
            prior = copy.deepcopy(self.previous)
            prior["records"] = records
            self.write(self.prior_path, self.reseal(prior))
            self.anchor = prior["proof"]["digest"]
            self.check(accepted=False)
            self.paired_cli(accepted=False)

    def test_postrevocation_different_valid_fork_rejected(self):
        self.write(self.prior_path, self.revoked)
        self.anchor = self.revoked["proof"]["digest"]
        fork = copy.deepcopy(self.revoked)
        fork["records"].pop()
        fork["records"][-5]["data"]["request_key"] = "other-second"
        request = fork["records"][-1]["data"]["request"]
        request["request_key"] = "other-second"
        fork["records"][-1]["data"]["request_hash"] = fixture.digest(request)
        fork["records"].append(copy.deepcopy(self.revoked["records"][-1]))
        self.write(self.path, self.reseal(fork))
        verify.verify(self.path)
        self.check(accepted=False)
        self.paired_cli(accepted=False)

    def test_distinct_files_read_and_validated_once(self):
        opened = []
        original = Path.open

        def monitor(path, *args, **kwargs):
            opened.append((path, args))
            return original(path, *args, **kwargs)

        before = self.snapshot()
        with patch.object(Path, "open", monitor), patch.object(
                verify, "_verify_envelope", wraps=verify._verify_envelope) as validate:
            self.assert_output(verify.verify(
                self.path, previous_envelope=self.prior_path,
                expected_previous_proof=self.anchor), 5, 5)
            self.assertEqual(validate.call_count, 2)
        self.assertCountEqual(opened, [(self.path, ("rb",)), (self.prior_path, ("rb",))])
        self.assertEqual(self.snapshot(), before)

    def test_same_file_read_and_validated_once(self):
        with patch.object(verify, "_load_envelope", wraps=verify._load_envelope) as load, patch.object(
                verify, "_verify_envelope", wraps=verify._verify_envelope) as validate:
            result = verify.verify(self.prior_path, previous_envelope=self.prior_path,
                                   expected_previous_proof=self.anchor)
            self.assert_output(result, 5, 0)
            load.assert_called_once_with(self.prior_path)
            self.assertEqual(validate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
