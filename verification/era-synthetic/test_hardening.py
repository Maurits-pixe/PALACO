"""Additional hardening regressions, not official or additional local WF mappings."""
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


class AnchorHardening(unittest.TestCase):
    def setUp(self):
        work = HERE / ".runtime"
        work.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "input.envelope.json"
        store = fixture.Store(Path(self.directory.name) / "state.sqlite", SOURCE)
        try:
            store.submit(fixture.request())
            store.revoke()
            self.envelope = store.export()
        finally:
            store.close()
        self.proof = self.envelope["proof"]["digest"]
        self.write(self.envelope)

    def write(self, envelope):
        self.path.write_bytes(fixture.canonical(envelope))

    def cli(self, *args, accepted=True):
        before = self.path.read_bytes()
        self.path.chmod(0o444)
        try:
            result = subprocess.run(
                [sys.executable, "-I", str(HERE / "verify.py"), str(self.path), *args],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0 if accepted else 1,
                             result.stdout + result.stderr)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(json.loads(result.stdout)["result"],
                             "VERIFIED_SYNTHETIC_ONLY" if accepted else "REJECTED")
            return json.loads(result.stdout)
        finally:
            self.path.chmod(0o644)

    @staticmethod
    def reseal(envelope):
        previous = fixture.digest({k: envelope[k] for k in ("schema", "source", "flags")})
        hashes = {}
        for index, record in enumerate(envelope["records"], 1):
            old_hash = record["hash"]
            for key in ("identity", "evidence", "decision", "authorization"):
                value = record["data"].get(key)
                if type(value) is str and value in hashes:
                    record["data"][key] = hashes[value]
            record["seq"], record["prev"] = index, previous
            record["hash"] = fixture.digest(
                {k: record[k] for k in ("seq", "kind", "data", "prev")})
            hashes[old_hash] = previous = record["hash"]
        envelope["proof"]["digest"] = fixture.digest(
            {k: envelope[k] for k in ("schema", "source", "flags", "records")})
        return envelope

    def test_independent_cli_both_anchors(self):
        # Isolated Python receives only the envelope and caller's expectations.
        result = self.cli("--expected-source-commit", SOURCE, "--expected-proof", self.proof)
        self.assertEqual(result["source_commit"], SOURCE)
        self.assertEqual(result["proof"], self.proof)
        for name in ("source", "proof"):
            self.assertIs(result[name + "_anchor_supplied"], True)
            self.assertIs(result[name + "_anchor_matched"], True)
        self.assertIs(result["execution"], False)
        self.assertIs(result["authenticity"], False)

    def test_optional_single_anchors_and_legacy(self):
        for source, proof in ((False, False), (True, False), (False, True)):
            with self.subTest(source=source, proof=proof):
                args = []
                kwargs = {}
                if source:
                    args += ["--expected-source-commit", SOURCE]
                    kwargs["expected_source_commit"] = SOURCE
                if proof:
                    args += ["--expected-proof", self.proof]
                    kwargs["expected_proof"] = self.proof
                result = self.cli(*args)
                self.assertEqual(verify.verify(self.path, **kwargs), result)
                for name, supplied in (("source", source), ("proof", proof)):
                    self.assertIs(result[name + "_anchor_supplied"], supplied)
                    self.assertIs(result[name + "_anchor_matched"], True if supplied else None)

    def test_api_rejects_malformed_wrong_type_and_mismatched_anchors(self):
        class Text(str):
            pass

        for keyword, length, mismatch in (
                ("expected_source_commit", 40, OTHER_SOURCE),
                ("expected_proof", 64, "0" * 64 if self.proof != "0" * 64 else "1" * 64)):
            for value in ("", "a" * (length - 1), "a" * (length + 1),
                          "A" * length, "g" * length, "a" * length + "\n",
                          " " + "a" * length, None, 0, True, [], {}, b"a" * length,
                          Text("a" * length), mismatch):
                with self.subTest(keyword=keyword, value=value):
                    before = self.path.read_bytes()
                    with self.assertRaises(ValueError):
                        verify.verify(self.path, **{keyword: value})
                    self.assertEqual(self.path.read_bytes(), before)

    def test_cli_rejects_invalid_or_mismatched_anchor_values(self):
        for option, length, mismatch in (
                ("--expected-source-commit", 40, OTHER_SOURCE),
                ("--expected-proof", 64, "0" * 64 if self.proof != "0" * 64 else "1" * 64)):
            for value in ("", "a" * (length - 1), "a" * (length + 1),
                          "A" * length, "g" * length, "a" * length + "\n", mismatch):
                with self.subTest(option=option, value=value):
                    self.cli(option, value, accepted=False)
            before = self.path.read_bytes()
            result = subprocess.run(
                [sys.executable, str(HERE / "verify.py"), str(self.path), option],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(self.path.read_bytes(), before)

    def test_rehashed_source_rewrite_requires_caller_source_anchor(self):
        candidate = copy.deepcopy(self.envelope)
        candidate["source"]["commit"] = OTHER_SOURCE
        self.write(self.reseal(candidate))
        self.cli()
        self.cli("--expected-source-commit", SOURCE, accepted=False)
        with self.assertRaises(ValueError):
            verify.verify(self.path, expected_source_commit=SOURCE)

    def test_valid_truncation_requires_original_trusted_proof_anchor(self):
        candidate = copy.deepcopy(self.envelope)
        candidate["records"].pop()  # Remove terminal revocation and recompute the structural proof.
        self.write(self.reseal(candidate))
        self.cli()
        self.cli("--expected-source-commit", SOURCE)
        self.cli("--expected-proof", self.proof, accepted=False)
        with self.assertRaises(ValueError):
            verify.verify(self.path, expected_source_commit=SOURCE, expected_proof=self.proof)

    def test_matching_anchors_do_not_bypass_full_validation(self):
        for mutation in ("execution", "decision"):
            candidate = copy.deepcopy(self.envelope)
            if mutation == "execution":
                candidate["flags"]["execution"] = True
            else:
                candidate["records"][2]["data"]["decision"] = "EXECUTE"
            self.write(self.reseal(candidate))
            proof = candidate["proof"]["digest"]
            self.cli("--expected-source-commit", SOURCE, "--expected-proof", proof, accepted=False)
            with self.assertRaises(ValueError):
                verify.verify(self.path, expected_source_commit=SOURCE, expected_proof=proof)


class CapacityHardening(unittest.TestCase):
    def setUp(self):
        work = HERE / ".runtime"
        work.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.directory.cleanup)

    def check_capacity(self, cap, groups):
        db = Path(self.directory.name) / f"capacity-{cap}.sqlite"
        store = fixture.Store(db, SOURCE)
        try:
            receipts = [store.submit(fixture.request(f"key-{index}")) for index in range(groups)]
            self.assertEqual(len(store.export()["records"]), groups * 5)

            def unchanged(operation, error=None):
                before = (db.read_bytes(), store.export(), store.db.execute(
                    "SELECT * FROM requests ORDER BY key").fetchall())
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        operation()
                else:
                    self.assertEqual(operation(), receipts[0])
                self.assertEqual((db.read_bytes(), store.export(), store.db.execute(
                    "SELECT * FROM requests ORDER BY key").fetchall()), before)

            changed = fixture.request("key-0")
            changed["world"] = "changed"
            for revoked in (False, True):
                if revoked:
                    store.revoke()
                    self.assertEqual(len(store.export()["records"]), groups * 5 + 1)
                    snapshot = (db.read_bytes(), store.export())
                    store.revoke()
                    self.assertEqual((db.read_bytes(), store.export()), snapshot)
                with patch.object(store, "_append", wraps=store._append) as append:
                    unchanged(lambda: store.submit(fixture.request("fresh")),
                              "revoked" if revoked else "record bound exceeded")
                    append.assert_not_called()
                unchanged(lambda: store.submit(fixture.request("key-0")))
                unchanged(lambda: store.submit(changed), "request key conflict")
                invalid = fixture.request("invalid")
                invalid["world"] = "changed"
                unchanged(lambda: store.submit(invalid), "denied synthetic fixture")
                snapshot = store.export()
                store.close()
                store = fixture.Store(db, SOURCE)
                self.assertEqual(store.export(), snapshot)
                for index, receipt in enumerate(receipts):
                    self.assertEqual(store.submit(fixture.request(f"key-{index}")), receipt)
                self.assertEqual(store.export(), snapshot)
            envelope = Path(self.directory.name) / f"capacity-{cap}.json"
            envelope.write_bytes(fixture.canonical(store.export()))
            self.assertEqual(verify.verify(envelope)["records"], groups * 5 + 1)
        finally:
            store.close()

    def test_exact_reserved_capacity_reduced_bounds(self):
        for cap, groups in ((6, 1), (11, 2)):
            with self.subTest(cap=cap), patch.object(fixture, "MAX_RECORDS", cap):
                self.check_capacity(cap, groups)

    def test_production_bound_199_groups_then_revocation(self):
        self.assertEqual(fixture.MAX_RECORDS, 1000)
        self.check_capacity(1000, 199)

    def test_legacy_full_log_does_not_bypass_cap(self):
        db = Path(self.directory.name) / "legacy.sqlite"
        store = fixture.Store(db, SOURCE)
        try:
            with patch.object(fixture, "MAX_RECORDS", 6):
                receipt = store.submit(fixture.request())
            # Model an already-full legacy store without changing its records or migrating it.
            with patch.object(fixture, "MAX_RECORDS", 5):
                before = (db.read_bytes(), store.export())
                with self.assertRaisesRegex(ValueError, "record bound exceeded"):
                    store.revoke()
                self.assertEqual(store.submit(fixture.request()), receipt)
                with self.assertRaisesRegex(ValueError, "record bound exceeded"):
                    store.submit(fixture.request("fresh"))
                self.assertEqual((db.read_bytes(), store.export()), before)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
