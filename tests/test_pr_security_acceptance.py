"""GO-20 v27: consolidated security acceptance, tamper and fail-closed tests."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_security_acceptance import (
    REQUIRED_GATES, construct, verify,
)
from test_pr_governance_history import GovernanceHistoryTests


class InvalidAcceptanceTests(unittest.TestCase):
    def test_absent_report(self):
        self.assertIn("invalid_report", verify(None, None)["errors"])

    def test_missing_input_set(self):
        self.assertIn("invalid_independent_inputs:ValueError",
                      verify({}, {})["errors"])

    def test_missing_source_on_construct(self):
        with self.assertRaises(ValueError):
            construct({"history": {}})

    def test_noncanonical_input_fails_closed(self):
        with self.assertRaises(ValueError):
            construct({"history": {3}, "independent_pin": {},
                       "controller_trust": {}})


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        fixture = GovernanceHistoryTests("test_valid_unchanged_history_still_denies")
        fixture.setUp()
        self.sources = {
            "history": fixture.history,
            "independent_pin": fixture.pin,
            "controller_trust": fixture.trust,
        }
        self.report = construct(self.sources)

    def check(self):
        return verify(self.report, self.sources)

    def test_valid_report_recomputed_without_release(self):
        v = self.check()
        self.assertTrue(v["acceptance_valid"], v["errors"])
        self.assertTrue(self.report["technical_acceptance"])
        self.assertEqual(set(self.report["acceptance_gates"]), set(REQUIRED_GATES))
        self.assertFalse(self.report["independently_attested"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for key in ("release_authorized", "merge_authorized", "deployment_authorized"):
            self.assertFalse(v[key])
            self.assertFalse(self.report[key])

    def test_tampered_review_status(self):
        self.report["verification"]["evidence_valid"] = False
        self.assertIn("report_mismatch:verification", self.check()["errors"])

    def test_forged_acceptance_status(self):
        self.report["technical_acceptance"] = False
        self.assertIn("report_mismatch:technical_acceptance", self.check()["errors"])

    def test_forged_release_authorization(self):
        self.report["release_authorized"] = True
        self.assertIn("report_mismatch:release_authorized", self.check()["errors"])

    def test_missing_gate(self):
        del self.report["acceptance_gates"]["release_prohibition"]
        self.assertIn("report_mismatch:acceptance_gates", self.check()["errors"])

    def test_checksum_replacement(self):
        self.report["report_sha256"] = "0" * 64
        self.assertIn("report_mismatch:report_sha256", self.check()["errors"])

    def test_missing_input_component(self):
        del self.report["input_component_sha256"]["controller_trust"]
        self.assertIn("report_mismatch:input_component_sha256", self.check()["errors"])

    def test_changed_independent_anchor(self):
        self.sources["independent_pin"]["last_policy_sha256"] = "0" * 64
        self.assertIn("technical_gates_failed", self.check()["errors"])

    def test_revoked_governance_controller(self):
        self.sources["controller_trust"]["controllers"]["governance-controller"]["status"] = "revoked"
        self.assertIn("technical_gates_failed", self.check()["errors"])

    def test_snapshot_removed(self):
        self.sources["history"]["snapshots"].pop()
        self.assertIn("technical_gates_failed", self.check()["errors"])

    def test_policy_release_prohibition_removed(self):
        self.sources["history"]["snapshots"][1]["policy"]["prohibited_capabilities"].remove("merge")
        self.assertIn("technical_gates_failed", self.check()["errors"])

    def test_all_technical_gates_fail_on_invalid_history(self):
        self.sources["history"]["transitions"][0]["signature_ed25519_hex"] = "0" * 128
        report = construct(self.sources)
        self.assertFalse(report["technical_acceptance"])
        self.assertTrue(all(gate is False for gate in report["acceptance_gates"].values()))
        self.assertEqual((report["decision"], report["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(verify(report, self.sources)["acceptance_valid"])

    def test_boolean_string_forgery(self):
        self.report["independently_attested"] = "false"
        self.assertIn("report_mismatch:independently_attested", self.check()["errors"])


if __name__ == "__main__":
    unittest.main()
