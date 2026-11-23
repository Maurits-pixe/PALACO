"""GO-20 v36: concurrent restore idempotence and conflict isolation tests."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_concurrent_recovery import REQUEST_SCHEMA, evaluate
from test_pr_recovery_simulation import SegmentedRestoreTests


class InvalidClaims(unittest.TestCase):
    def test_missing_fails_closed(self):
        v = evaluate(None)
        self.assertFalse(v["claims_valid"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["restore_performed"])

    def test_invalid_batch_fails_closed(self):
        self.assertIn("invalid_request_batch",
                      evaluate({"schema": REQUEST_SCHEMA, "requests": []})["errors"])

    def test_hostile_non_json_values_rejected(self):
        self.assertFalse(evaluate({"schema": REQUEST_SCHEMA, "requests": [{3, 4}]})["claims_valid"])


class ConcurrentClaims(unittest.TestCase):
    def setUp(self):
        base = SegmentedRestoreTests("test_complete_memory_only_restore_verifies")
        base.setUp()
        self.request = {
            "request_id": "restore-001",
            "segments": base.package,
            "manifest": base.manifest,
            "independent_pin": base.pin,
        }

    def check(self, batch):
        return evaluate({"schema": REQUEST_SCHEMA, "requests": batch})

    def test_one_request_one_sandbox_commit(self):
        v = self.check([self.request])
        self.assertTrue(v["claims_valid"], v["errors"])
        self.assertEqual((v["new_sandbox_commits"], v["sandbox_ledger_rows"]), (1, 1))
        self.assertEqual(v["idempotent_replays"], 0)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["production_write_performed"])

    def test_twelve_simultaneous_duplicate_requests_single_commit(self):
        batch = [copy.deepcopy(self.request) for _ in range(12)]
        v = self.check(batch)
        self.assertTrue(v["claims_valid"], v["errors"])
        self.assertEqual(v["new_sandbox_commits"], 1)
        self.assertEqual(v["idempotent_replays"], 11)
        self.assertEqual(v["sandbox_ledger_rows"], 1)

    def test_same_material_different_request_ids_replay(self):
        batch = [copy.deepcopy(self.request) for _ in range(4)]
        for i, item in enumerate(batch):
            item["request_id"] = "different-" + str(i)
        v = self.check(batch)
        self.assertTrue(v["claims_valid"], v["errors"])
        self.assertEqual(v["new_sandbox_commits"], 1)
        self.assertEqual(v["idempotent_replays"], 3)

    def test_same_request_id_different_valid_segment_order_conflicts(self):
        other = copy.deepcopy(self.request)
        other["segments"]["parts"].reverse()
        v = self.check([self.request, other])
        self.assertFalse(v["claims_valid"])
        self.assertEqual(v["new_sandbox_commits"], 1)
        self.assertEqual(v["conflicts_rejected"], 1)
        self.assertEqual(v["sandbox_ledger_rows"], 1)
        self.assertIn("conflicting_idempotency_key", v["errors"])

    def test_unique_invalid_source_rejects_entire_batch_before_sql(self):
        bad = copy.deepcopy(self.request)
        bad["request_id"] = "bad-claim"
        bad["segments"]["parts"].pop()
        v = self.check([self.request, bad])
        self.assertFalse(v["claims_valid"])
        self.assertEqual(v["new_sandbox_commits"], 0)
        self.assertEqual(v["sandbox_ledger_rows"], 0)

    def test_changed_independent_pin_rejected_preflight(self):
        bad = copy.deepcopy(self.request)
        bad["independent_pin"]["manifest_sha256"] = "0" * 64
        v = self.check([bad])
        self.assertFalse(v["claims_valid"])
        self.assertEqual(v["new_sandbox_commits"], 0)

    def test_duplicate_parts_rejected_before_sql(self):
        bad = copy.deepcopy(self.request)
        bad["segments"]["parts"][-1] = copy.deepcopy(bad["segments"]["parts"][0])
        self.assertEqual(self.check([bad])["sandbox_ledger_rows"], 0)

    def test_multiple_request_outcomes_indexed(self):
        batch = [copy.deepcopy(self.request) for _ in range(6)]
        v = self.check(batch)
        self.assertEqual([r["index"] for r in v["request_outcomes"]], list(range(6)))

    def test_forged_authorization_never_accepted(self):
        bad = copy.deepcopy(self.request)
        bad["manifest"]["repository"] = "unauthorized/repo"
        v = self.check([bad])
        self.assertFalse(v["claims_valid"])
        for key in ("release_authorized", "merge_authorized",
                    "deployment_authorized", "production_commit_performed",
                    "restore_performed"):
            self.assertFalse(v[key])

    def test_long_request_id_denied(self):
        bad = copy.deepcopy(self.request)
        bad["request_id"] = "x" * 129
        self.assertIn("invalid_request:0", self.check([bad])["errors"])

    def test_empty_request_id_denied(self):
        bad = copy.deepcopy(self.request)
        bad["request_id"] = ""
        self.assertIn("invalid_request:0", self.check([bad])["errors"])

    def test_batch_larger_than_limit_denied(self):
        batch = [copy.deepcopy(self.request) for _ in range(13)]
        self.assertIn("invalid_request_batch", self.check(batch)["errors"])

    def test_each_call_has_no_persistent_ledger(self):
        first = self.check([self.request])
        second = self.check([self.request])
        self.assertEqual(first["new_sandbox_commits"], 1)
        self.assertEqual(second["new_sandbox_commits"], 1)
        self.assertFalse(first["production_commit_performed"])


if __name__ == "__main__":
    unittest.main()
