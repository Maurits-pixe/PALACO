"""Contract tests for the offline PR assessment gate."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pr_hold_assessor.py"
spec = importlib.util.spec_from_file_location("pr_hold_assessor", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AssessorTests(unittest.TestCase):
    def valid(self):
        return {
            "repository": "Maurits-pixe/PALACO",
            "head_sha": "a" * 40,
            "checks": {"test": "success", "lint": "success"},
            "reviews": "approved",
            "evidence": ["local-run-001"],
            "go13_release_authorized": True,
        }

    def test_all_green_never_grants_authority(self):
        result = module.assess(self.valid())
        self.assertTrue(result["technical_inputs_complete"])
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["authorization"], "DENY")

    def test_missing_evidence_fails_closed(self):
        input_data = self.valid()
        input_data.pop("evidence")
        self.assertIn("missing_evidence", module.assess(input_data)["reasons"])

    def test_pending_check_fails_closed(self):
        input_data = self.valid()
        input_data["checks"]["lint"] = "pending"
        self.assertIn("check_not_success:lint", module.assess(input_data)["reasons"])

    def test_release_authorization_missing(self):
        input_data = self.valid()
        input_data["go13_release_authorized"] = False
        self.assertIn("go13_not_authorized", module.assess(input_data)["reasons"])

    def test_rejects_malformed_input(self):
        self.assertEqual(module.assess([])["authorization"], "DENY")
        input_data = self.valid()
        input_data["head_sha"] = "not-a-sha"
        self.assertIn("invalid_head_sha", module.assess(input_data)["reasons"])

    def test_rejects_invalid_check_state(self):
        input_data = self.valid()
        input_data["checks"] = {"test": "unknown"}
        self.assertIn("invalid_check_entry", module.assess(input_data)["reasons"])


if __name__ == "__main__":
    unittest.main()
