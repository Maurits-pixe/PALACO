"""GO-20 v40: read-only cross-instance handoff evidence checks."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pr_recovery_handoff import canonical, digest, verify

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.primary = [
            dict(request_id="one", manifest_sha256=A, pin_sha256=B, segments_sha256=C),
            dict(request_id="two", manifest_sha256=D, pin_sha256=B, segments_sha256=C),
        ]
        self.candidate = [dict(x) for x in self.primary]
        self.pin = {"schema": "palaco.go20-restore-handoff-pin.v1",
                    "primary_sha256": digest(canonical(self.primary)), "minimum_rows": 2}

    def check(self):
        return verify(self.primary, self.candidate, self.pin)

    def test_consistent_snapshots_remain_hold(self):
        v = self.check()
        self.assertTrue(v["handoff_consistent"], v["errors"])
        self.assertEqual(v["rows_compared"], 2)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        for name in ("failover_authorized", "release_authorized", "merge_authorized",
                     "deployment_authorized", "production_commit_performed"):
            self.assertFalse(v[name])

    def test_order_does_not_matter(self):
        self.candidate.reverse()
        self.assertTrue(self.check()["handoff_consistent"])

    def test_missing_latest_claim(self):
        self.candidate.pop()
        self.assertIn("snapshot_divergence_or_missing_claims", self.check()["errors"])

    def test_divergent_digest(self):
        self.candidate[0]["segments_sha256"] = A
        self.assertFalse(self.check()["handoff_consistent"])

    def test_replaced_source_anchor(self):
        self.pin["primary_sha256"] = D
        self.assertIn("source_anchor_mismatch", self.check()["errors"])

    def test_retention_floor(self):
        self.pin["minimum_rows"] = 3
        self.assertIn("source_retention_floor", self.check()["errors"])

    def test_boolean_floor_rejected(self):
        self.pin["minimum_rows"] = True
        self.assertIn("invalid_independent_source_anchor", self.check()["errors"])

    def test_malformed_anchor_rejected(self):
        del self.pin["schema"]
        self.assertFalse(self.check()["handoff_consistent"])

    def test_duplicate_id_denied(self):
        self.candidate.append(dict(self.candidate[0]))
        self.assertIn("malformed_ledger_snapshot", self.check()["errors"])

    def test_duplicate_material_denied(self):
        duplicate = dict(self.candidate[0])
        duplicate["request_id"] = "other"
        self.candidate.append(duplicate)
        self.assertFalse(self.check()["handoff_consistent"])

    def test_nonhex_rejected(self):
        self.candidate[0]["manifest_sha256"] = "z" * 64
        self.assertFalse(self.check()["handoff_consistent"])

    def test_invalid_row_shape_rejected(self):
        self.candidate[0]["extra"] = True
        self.assertFalse(self.check()["handoff_consistent"])

    def test_unauthenticated_extra_claim_rejected(self):
        self.candidate.append(dict(request_id="three",
                                   manifest_sha256=A, pin_sha256=D, segments_sha256=C))
        self.assertFalse(self.check()["handoff_consistent"])

    def test_no_failover_even_on_error(self):
        self.candidate = []
        v = self.check()
        self.assertFalse(v["failover_authorized"])
        self.assertEqual(v["authorization"], "DENY")


if __name__ == "__main__":
    unittest.main()
