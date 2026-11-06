"""Deterministic mutation tests for synthetic source-HOLD drift detection."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

import postmerge_scope as scope


class PostMergeScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = scope.read_sources(Path(__file__).resolve().parents[2])

    def test_merged_source_contract_matches_all_expected_hold_checks(self) -> None:
        results = scope.check_sources(self.sources)
        self.assertEqual(set(results), set(scope.CHECKS))
        self.assertEqual(len(results), 15)
        self.assertTrue(all(results.values()), [name for name, ok in results.items() if not ok])

    def mutate(self, file: str, original: str, altered: str, must_fail: str) -> None:
        candidate = deepcopy(self.sources)
        self.assertIn(original, candidate[file], f"missing original invariant: {file}")
        candidate[file] = candidate[file].replace(original, altered, 1)
        findings = scope.check_sources(candidate)
        self.assertFalse(findings[must_fail], f"must fail closed: {must_fail}")

    def test_nonloopback_listener_fails(self) -> None:
        self.mutate("listener", "[127, 0, 0, 1]", "[0, 0, 0, 0]", "fixed_loopback_listener")

    def test_open_identity_mode_fails(self) -> None:
        self.mutate("server", 'mode != "SYNTHETIC_ONLY"',
                    'mode != "PRODUCTION"', "synthetic_mode_required")

    def test_remote_oidc_issuer_fails(self) -> None:
        self.mutate("server", 'http://127.0.0.1:8089/realms/rio-synthetic',
                    'https://identity.example.invalid/realm', "fixed_synthetic_issuer")

    def test_server_status_grant_fails(self) -> None:
        self.mutate("server", '"accountActive":false,',
                    '"accountActive":true,', "server_status_closed")

    def test_session_bound_account_grant_fails(self) -> None:
        self.mutate("server", '"canOpenContact":false,"account1":"HOLD"})))',
                    '"canOpenContact":true,"account1":"HOLD"})))', "own_account_closed")

    def test_consent_receipt_contact_grant_fails(self) -> None:
        self.mutate("consent", '"canOpenContact": false,',
                    '"canOpenContact": true,', "consent_receipt_closed")

    def test_registration_enabled_fails(self) -> None:
        self.mutate("fixture", '"registrationAllowed": False',
                    '"registrationAllowed": True', "fixture_registration_disabled")

    def test_real_callback_fails(self) -> None:
        self.mutate("fixture", 'CALLBACK = "https://localhost:8088/auth/callback"',
                    'CALLBACK = "https://service.example.invalid/auth/callback"',
                    "synthetic_fixture_callback")

    def test_workflow_write_token_fails(self) -> None:
        self.mutate("workflow", "contents: read", "contents: write", "ci_read_only_token")

    def test_absent_human_hold_fails(self) -> None:
        self.mutate("gate", "HUMAN REVIEW PENDING", "HUMAN REVIEW PASSED", "review_gate_hold")

    def test_unreadable_manifest_and_unknown_paths_fail(self) -> None:
        candidate = deepcopy(self.sources)
        candidate.pop("gate")
        with self.assertRaises(ValueError):
            scope.check_sources(candidate)
        candidate = deepcopy(self.sources)
        candidate["new"] = "SYNTHETIC_ONLY"
        with self.assertRaises(ValueError):
            scope.check_sources(candidate)


if __name__ == "__main__":
    unittest.main()
