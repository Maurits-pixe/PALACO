"""Negative and positive synthetic review-record contract checks; no secrets."""
from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("t04_review_gate", ROOT / "review_gate.py")
assert SPEC and SPEC.loader
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def template():
    return json.loads((ROOT / "review" / "t04-review-template.json").read_text(encoding="utf-8"))


class ReviewGateTests(unittest.TestCase):
    def test_template_is_only_a_valid_blocked_record(self):
        result = check.validate(template())
        self.assertEqual(result["structure"], "VALID")
        self.assertEqual(result["humanAcceptance"], "HOLD")
        self.assertEqual(result["statuses"], {"BLOCKED": 5, "NOT_RUN": 6, "FAIL": 0, "PASS": 0})
        self.assertFalse(result["physicalAndroidVerified"])
        self.assertFalse(result["independentReviewAccepted"])

    def test_unknown_data_and_authority_switches_rejected(self):
        for key, value in [("account1", "ACTIVE"), ("authority", "OWNER"),
                           ("humanAcceptance", "PASS"), ("scope", "REAL"),
                           ("pr", True), ("candidateHead", "fake")]:
            with self.subTest(key=key):
                item = template()
                item[key] = value
                with self.assertRaises(check.InvalidEvidence):
                    check.validate(item)
        bad = template()
        bad["password"] = "synthetic-unwanted-key"
        with self.assertRaises(check.InvalidEvidence):
            check.validate(bad)

    def test_missing_repeated_and_unexpected_cases_rejected(self):
        original = template()
        for operation in [
            lambda v: v["cases"].pop(),
            lambda v: v["cases"].__setitem__(0, deepcopy(v["cases"][1])),
            lambda v: v["cases"][0].update({"cookie": "unsafe"}),
            lambda v: v["cases"][0].update({"status": "VERIFIED"}),
        ]:
            item = deepcopy(original)
            operation(item)
            with self.assertRaises(check.InvalidEvidence):
                check.validate(item)

    def test_fabricated_pass_without_human_evidence_rejected(self):
        for index in (0, 5, 7):
            item = template()
            item["cases"][index]["status"] = "PASS"
            item["cases"][index]["reason"] = "NONE"
            with self.assertRaises(check.InvalidEvidence):
                check.validate(item)

    def test_unsafe_refs_and_fabricated_physical_pass_rejected(self):
        item = template()
        target = item["cases"][0]
        target.update({"status": "PASS", "reason": "NONE", "reviewerRole": "ACCESSIBILITY",
                       "independenceAttested": True, "evidenceIds": ["EVD-PHYSICAL-01"]})
        with self.assertRaises(check.InvalidEvidence):
            check.validate(item)
        item["physicalAccess"] = "HUMAN_ATTESTED_SYNTHETIC_ONLY"
        self.assertEqual(check.validate(item)["humanAcceptance"], "HOLD")
        for value in ["https://example.com/?token=abc", "EVD-secret@email.com"]:
            item["cases"][0]["evidenceIds"] = [value]
            with self.assertRaises(check.InvalidEvidence):
                check.validate(item)

    def test_even_all_recorded_pass_cannot_authorize_operation(self):
        item = template()
        item["physicalAccess"] = "HUMAN_ATTESTED_SYNTHETIC_ONLY"
        for case in item["cases"]:
            case.update({"status": "PASS", "reason": "NONE", "independenceAttested": True,
                         "reviewerRole": check.CASES[case["id"]],
                         "evidenceIds": ["EVD-SANITIZED-0001"]})
        result = check.validate(item)
        self.assertEqual(result["statuses"]["PASS"], 11)
        self.assertEqual(result["humanAcceptance"], "HOLD")
        self.assertFalse(result["independentReviewAccepted"])

    def test_duplicate_json_key_rejected_without_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "duplicate.json"
            file.write_text('{"humanAcceptance":"PASS","humanAcceptance":"HOLD"}', encoding="utf-8")
            captured = io.StringIO()
            with redirect_stdout(captured):
                self.assertEqual(check.main(["review_gate.py", str(file)]), 1)
            self.assertEqual(captured.getvalue().strip(), "RIO_T04_REVIEW_RECORD REJECTED")

    def test_cli_does_not_echo_secrets_or_bad_content(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "evidence.json"
            file.write_text('{"private":"SENSITIVE-NEVER-ECHO"}', encoding="utf-8")
            captured = io.StringIO()
            with redirect_stdout(captured):
                outcome = check.main(["review_gate.py", str(file)])
            self.assertEqual(outcome, 1)
            self.assertNotIn("SENSITIVE", captured.getvalue())
            self.assertIn("REJECTED", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
