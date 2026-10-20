"""Pinned local known answers; not external conformance or authorization evidence."""
import copy
import hashlib
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
VECTOR = HERE / "vectors" / "v1.json"


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def actual_sha(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class KnownAnswerVectors(unittest.TestCase):
    def setUp(self):
        original = VECTOR.read_bytes()
        self.vector = json.loads(original)
        self.addCleanup(lambda: self.assertEqual(VECTOR.read_bytes(), original))
        runtime = HERE / ".runtime"
        runtime.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.closed = self.vector["closed_envelope"]
        self.open = copy.deepcopy(self.closed)
        self.open["records"] = self.open["records"][:5]
        self.open["proof"] = copy.deepcopy(self.vector["open_proof"])
        self.path = self.work / "closed.json"
        self.previous = self.work / "open.json"
        self.receipt = self.work / "receipt.json"
        self.write(self.path, self.closed)
        self.write(self.previous, self.open)
        self.write(self.receipt, self.vector["receipt"])
        self.source = self.closed["source"]["commit"]
        self.options = {"expected_source_commit": self.source,
                        "expected_proof": self.closed["proof"]["digest"]}

    def write(self, path, value):
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")

    def assertStrictEqual(self, actual, expected):
        self.assertIs(type(actual), type(expected))
        if type(expected) is dict:
            self.assertEqual(actual.keys(), expected.keys())
            for key in expected:
                self.assertStrictEqual(actual[key], expected[key])
        elif type(expected) is list:
            self.assertEqual(len(actual), len(expected))
            for left, right in zip(actual, expected):
                self.assertStrictEqual(left, right)
        else:
            self.assertEqual(actual, expected)

    def assertAnswer(self, answer):
        expected_bytes = answer["canonical_ascii"].encode("ascii")
        self.assertEqual(hashlib.sha256(expected_bytes).hexdigest(), answer["sha256"])
        for encode, digest in ((fixture.canonical, fixture.digest), (verify.encode, verify.sha)):
            self.assertEqual(encode(answer["input"]), expected_bytes)
            self.assertEqual(digest(answer["input"]), answer["sha256"])

    def test_vector_version_and_explicit_shape(self):
        self.assertEqual(set(self.vector), {
            "vector_version", "description", "canonical_cases", "request", "payload",
            "genesis", "open_proof", "closed_envelope", "receipt", "envelope_canonical_sha256"})
        self.assertStrictEqual(self.vector["vector_version"], "ERA_SYNTHETIC_LOCAL_VECTORS_V1")
        self.assertIs(type(self.vector["description"]), str)
        self.assertIn("artificial fixture binding", self.vector["description"])
        self.assertEqual([case["name"] for case in self.vector["canonical_cases"]],
                         ["empty_object", "sorted_nested", "unicode_controls"])
        for answer in [*self.vector["canonical_cases"],
                       *(self.vector[key] for key in ("request", "payload", "genesis"))]:
            self.assertEqual(set(answer), {"input", "canonical_ascii", "sha256"} |
                             ({"name"} if "name" in answer else set()))
            self.assertIs(type(answer["input"]), dict)
            self.assertIs(type(answer["canonical_ascii"]), str)
            self.assertTrue(answer["canonical_ascii"].isascii())
            self.assertIs(type(answer["sha256"]), str)
            self.assertRegex(answer["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(set(self.closed), {"schema", "source", "flags", "records", "proof"})
        self.assertStrictEqual(self.closed["schema"], "ERA_SYNTHETIC_V1")
        self.assertStrictEqual(self.closed["source"], {
            "repository": "https://github.com/Maurits-pixe/PALACO",
            "commit": "0000000000000000000000000000000000000000"})
        self.assertStrictEqual(self.closed["flags"], {
            "synthetic_only": True, "execution": False, "release": False})
        self.assertStrictEqual(self.vector["request"]["input"]["request_key"], "vector-1")
        self.assertStrictEqual(self.vector["request"]["input"]["world"], "WORLD-SYNTHETIC-1")
        self.assertEqual(set(self.vector["request"]["input"]), {
            "request_key", "identity", "world", "action", "authority", "evidence",
            "decision", "payload"})
        self.assertEqual(set(self.vector["payload"]["input"]), {"fixture", "version"})
        self.assertEqual(set(self.vector["genesis"]["input"]), {"schema", "source", "flags"})
        kinds = ["identity", "evidence", "decision", "authorization", "commit", "revocation"]
        fields = [{"request_key", "identity"}, {"identity", "evidence"},
                  {"evidence", "decision"}, {"decision", "authority", "execution"},
                  {"authorization", "request", "request_hash", "execution"},
                  {"authority", "execution"}]
        self.assertEqual(len(self.closed["records"]), 6)
        for seq, (record, kind, data_keys) in enumerate(zip(self.closed["records"], kinds, fields), 1):
            self.assertEqual(set(record), {"seq", "kind", "data", "prev", "hash"})
            self.assertStrictEqual(record["seq"], seq)
            self.assertStrictEqual(record["kind"], kind)
            self.assertEqual(set(record["data"]), data_keys)
            for key in ("prev", "hash"):
                self.assertRegex(record[key], r"^[0-9a-f]{64}$")
        for proof in (self.vector["open_proof"], self.closed["proof"]):
            self.assertEqual(set(proof), {"algorithm", "digest", "authenticity"})
            self.assertStrictEqual(proof["algorithm"], "SHA256")
            self.assertStrictEqual(proof["authenticity"], False)
            self.assertRegex(proof["digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(set(self.vector["receipt"]),
                         {"commit", "request_hash", "historical_record_only", "execution"})
        self.assertStrictEqual(self.vector["receipt"]["historical_record_only"], True)
        self.assertStrictEqual(self.vector["receipt"]["execution"], False)
        self.assertRegex(self.vector["envelope_canonical_sha256"], r"^[0-9a-f]{64}$")

    def test_primitive_canonical_ascii_and_digests(self):
        for answer in self.vector["canonical_cases"]:
            with self.subTest(case=answer["name"]):
                self.assertAnswer(answer)

    def test_request_payload_and_genesis_known_answers(self):
        self.assertStrictEqual(fixture.request("vector-1"), self.vector["request"]["input"])
        self.assertStrictEqual(self.vector["request"]["input"]["payload"],
                               self.vector["payload"]["input"])
        self.assertStrictEqual({key: self.closed[key] for key in ("schema", "source", "flags")},
                               self.vector["genesis"]["input"])
        for name in ("request", "payload", "genesis"):
            with self.subTest(name=name):
                self.assertAnswer(self.vector[name])

    def test_every_record_hash_open_closed_proofs_and_full_canonical_digest(self):
        previous = self.vector["genesis"]["sha256"]
        for record in self.closed["records"]:
            body = {key: record[key] for key in ("seq", "kind", "data", "prev")}
            self.assertEqual(record["prev"], previous)
            for digest in (actual_sha, fixture.digest, verify.sha):
                self.assertEqual(digest(body), record["hash"])
            previous = record["hash"]
        for envelope in (self.open, self.closed):
            body = {key: envelope[key] for key in ("schema", "source", "flags", "records")}
            for digest in (actual_sha, fixture.digest, verify.sha):
                self.assertEqual(digest(body), envelope["proof"]["digest"])
        expected = self.vector["envelope_canonical_sha256"]
        self.assertEqual(hashlib.sha256(canonical_bytes(self.closed)).hexdigest(), expected)
        self.assertEqual(fixture.digest(self.closed), expected)
        self.assertEqual(verify.sha(self.closed), expected)
        self.assertEqual(self.vector["receipt"]["commit"], self.closed["records"][4]["hash"])
        self.assertEqual(self.vector["receipt"]["request_hash"], self.vector["request"]["sha256"])

    def test_on_disk_producer_receipt_open_prefix_and_closed_envelope(self):
        store = fixture.Store(self.work / "state.sqlite", self.source)
        try:
            receipt = store.submit(copy.deepcopy(self.vector["request"]["input"]))
            self.assertStrictEqual(receipt, self.vector["receipt"])
            self.assertStrictEqual(store.export(expected_proof=self.vector["open_proof"]["digest"]),
                                   self.open)
            store.revoke(expected_proof=self.vector["open_proof"]["digest"])
            actual = store.export(expected_proof=self.options["expected_proof"])
            self.assertStrictEqual(actual, self.closed)
            self.assertEqual(hashlib.sha256(canonical_bytes(actual)).hexdigest(),
                             self.vector["envelope_canonical_sha256"])
        finally:
            store.close()

    def test_restart_historical_retry_after_revocation_never_renews_authority(self):
        database = self.work / "restart.sqlite"
        store = fixture.Store(database, self.source)
        try:
            store.submit(copy.deepcopy(self.vector["request"]["input"]))
            store.revoke()
        finally:
            store.close()
        store = fixture.Store(database, self.source)
        try:
            before = database.read_bytes()
            self.assertStrictEqual(store.submit(copy.deepcopy(self.vector["request"]["input"]),
                                               expected_proof=self.options["expected_proof"]),
                                   self.vector["receipt"])
            self.assertEqual(database.read_bytes(), before)
            fresh = copy.deepcopy(self.vector["request"]["input"])
            fresh["request_key"] = "vector-2"
            with self.assertRaisesRegex(ValueError, "revoked"):
                store.submit(fresh, expected_proof=self.options["expected_proof"])
            self.assertStrictEqual(store.export(), self.closed)
            self.assertEqual(database.read_bytes(), before)
        finally:
            store.close()

    def test_checker_api_and_isolated_cli_on_pinned_artifact_with_receipt_and_summary(self):
        before = {path.name: path.read_bytes() for path in self.work.iterdir()}
        with patch.object(fixture, "digest", side_effect=AssertionError("producer dependency")):
            result = verify.verify(self.path, **self.options, receipt=self.receipt, review_summary=True)
        run = subprocess.run([
            sys.executable, "-I", str(HERE / "verify.py"), str(self.path),
            "--expected-source-commit", self.source, "--expected-proof", self.options["expected_proof"],
            "--receipt", str(self.receipt), "--review-summary"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stderr, "")
        self.assertStrictEqual(json.loads(run.stdout), result)
        self.assertEqual(result["result"], "VERIFIED_SYNTHETIC_ONLY")
        self.assertStrictEqual(result["records"], 6)
        self.assertEqual(result["proof"], self.options["expected_proof"])
        self.assertEqual(result["source_commit"], self.source)
        for key in ("source_anchor_supplied", "source_anchor_matched",
                    "proof_anchor_supplied", "proof_anchor_matched"):
            self.assertStrictEqual(result[key], True)
        for key in ("execution", "authenticity"):
            self.assertStrictEqual(result[key], False)
        summary = result["review_summary"]
        for key, expected in {"committed_requests": 1, "records": 6, "revocation_sequence": 6,
                              "synthetic_only": True, "execution": False, "authenticity": False,
                              "release_authorized": False, "release_status": "HOLD"}.items():
            self.assertStrictEqual(summary[key], expected)
        self.assertStrictEqual(result["receipt_verification"], {
            "result": "VERIFIED_HISTORICAL_RECEIPT", "request_key": "vector-1", "commit_sequence": 5,
            **self.vector["receipt"], "authenticity": False})
        self.assertEqual({path.name: path.read_bytes() for path in self.work.iterdir()}, before)

    def test_checker_open_prefix_and_pinned_continuity(self):
        result = verify.verify(self.previous, expected_source_commit=self.source,
                               expected_proof=self.vector["open_proof"]["digest"])
        self.assertStrictEqual(result["records"], 5)
        self.assertEqual(result["proof"], self.vector["open_proof"]["digest"])
        result = verify.verify(self.path, **self.options, previous_envelope=self.previous,
                               expected_previous_proof=self.vector["open_proof"]["digest"])
        for key, expected in {"previous_records": 5, "added_records": 1, "continuity": "EXTENDED",
                              "previous_proof_anchor_matched": True}.items():
            self.assertStrictEqual(result[key], expected)
        self.assertEqual(result["previous_proof"], self.vector["open_proof"]["digest"])

    def test_equivalent_json_formatting_keeps_pinned_meaning(self):
        expected = verify.verify(self.path, **self.options)
        self.path.write_bytes(canonical_bytes(self.closed) + b"\n")
        self.assertStrictEqual(verify.verify(self.path, **self.options), expected)
        reordered = dict(reversed(list(self.closed.items())))
        self.path.write_text(json.dumps(reordered, indent=4) + "\n", encoding="utf-8")
        self.assertStrictEqual(verify.verify(self.path, **self.options), expected)
        self.assertEqual(actual_sha(json.loads(self.path.read_bytes())),
                         self.vector["envelope_canonical_sha256"])

    def test_rehashed_semantically_invalid_records_request_payload_hash_and_flags_reject(self):
        # Rehash only hostile copies, never derive or replace a baseline expected answer.
        for target in ("record", "decision", "payload", "request_hash", "flag"):
            with self.subTest(target=target):
                value = copy.deepcopy(self.closed)
                records = value["records"]
                if target == "record":
                    records[0]["data"]["identity"] = "other"
                elif target == "decision":
                    records[2]["data"]["decision"] = "EXECUTE"
                elif target == "payload":
                    records[4]["data"]["request"]["payload"]["version"] = 2
                    records[4]["data"]["request_hash"] = actual_sha(records[4]["data"]["request"])
                elif target == "request_hash":
                    records[4]["data"]["request_hash"] = "0" * 64
                else:
                    value["flags"]["execution"] = 0
                previous = actual_sha({key: value[key] for key in ("schema", "source", "flags")})
                replacements = {}
                for record in records:
                    old_hash = record["hash"]
                    for key in ("identity", "evidence", "decision", "authorization"):
                        reference = record["data"].get(key)
                        if type(reference) is str and reference in replacements:
                            record["data"][key] = replacements[reference]
                    record["prev"] = previous
                    record["hash"] = actual_sha({key: record[key] for key in ("seq", "kind", "data", "prev")})
                    replacements[old_hash] = previous = record["hash"]
                value["proof"]["digest"] = actual_sha(
                    {key: value[key] for key in ("schema", "source", "flags", "records")})
                self.write(self.path, value)
                with self.assertRaises(ValueError):
                    verify.verify(self.path)

    def test_tampered_receipts_including_integer_boolean_aliases_reject(self):
        for key, replacement in (("commit", "0" * 64), ("request_hash", "0" * 64),
                                 ("historical_record_only", 1), ("execution", 0),
                                 ("historical_record_only", False), ("execution", True)):
            with self.subTest(key=key, replacement=replacement):
                receipt = copy.deepcopy(self.vector["receipt"])
                receipt[key] = replacement
                self.write(self.receipt, receipt)
                with self.assertRaises(ValueError):
                    verify.verify(self.path, **self.options, receipt=self.receipt)

    def test_wrong_pinned_source_current_and_previous_proofs_reject(self):
        for overrides in ({"expected_source_commit": "1" * 40}, {"expected_proof": "0" * 64}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                verify.verify(self.path, **{**self.options, **overrides})
        with self.assertRaises(ValueError):
            verify.verify(self.path, **self.options, previous_envelope=self.previous,
                          expected_previous_proof="0" * 64)


if __name__ == "__main__":
    unittest.main()
