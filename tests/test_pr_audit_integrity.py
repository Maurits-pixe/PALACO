"""GO-20 v15 negative tests for externally anchored audit-export integrity."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pr_audit_integrity.py"
spec = importlib.util.spec_from_file_location("pr_audit_integrity", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AuditIntegrityTests(unittest.TestCase):
    def fixture(self):
        events = []
        head = module.ZERO
        for i, tenant in enumerate(("go20_alpha", "go20_beta"), 1):
            item = {
                "id": i, "operation": "INSERT", "actor_role": "go20test",
                "tenant_role": tenant, "entry_sha256": str(i) * 64,
                "previous_sha256": head,
            }
            item["event_sha256"] = module.canonical_hash(item)
            events.append(item)
            head = item["event_sha256"]
        return {"schema": module.SCHEMA, "events": events}, head

    def test_valid_export_stays_hold_deny(self):
        data, head = self.fixture()
        verdict = module.verify_export(data, head)
        self.assertTrue(verdict["integrity_valid"])
        self.assertEqual((verdict["decision"], verdict["authorization"]), ("HOLD", "DENY"))

    def test_modified_record_is_rejected(self):
        data, head = self.fixture()
        data["events"][0]["tenant_role"] = "forged"
        self.assertIn("event_digest_mismatch:0", module.verify_export(data, head)["errors"])

    def test_deleted_record_is_rejected(self):
        data, head = self.fixture()
        del data["events"][0]
        issues = module.verify_export(data, head)["errors"]
        self.assertIn("event_sequence_mismatch:0", issues)

    def test_reordered_records_are_rejected(self):
        data, head = self.fixture()
        data["events"].reverse()
        self.assertFalse(module.verify_export(data, head)["integrity_valid"])

    def test_external_anchor_rejects_forged_full_chain(self):
        data, head = self.fixture()
        data["events"][0]["tenant_role"] = "forged"
        data["events"][0]["event_sha256"] = module.canonical_hash({
            k: v for k, v in data["events"][0].items() if k != "event_sha256"
        })
        data["events"][1]["previous_sha256"] = data["events"][0]["event_sha256"]
        data["events"][1]["event_sha256"] = module.canonical_hash({
            k: v for k, v in data["events"][1].items() if k != "event_sha256"
        })
        self.assertIn("external_anchor_mismatch", module.verify_export(data, head)["errors"])

    def test_broken_predecessor(self):
        data, head = self.fixture()
        data["events"][1]["previous_sha256"] = module.ZERO
        self.assertIn("broken_chain:1", module.verify_export(data, head)["errors"])

    def test_missing_external_anchor(self):
        data, _ = self.fixture()
        self.assertIn("invalid_external_anchor", module.verify_export(data, None)["errors"])

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"schema":"x","schema":"y"}', object_pairs_hook=module.unique_pairs)

    def test_invalid_record_does_not_throw(self):
        data, head = self.fixture()
        data["events"][0] = ["not a record"]
        result = module.verify_export(data, head)
        self.assertIn("invalid_event:0", result["errors"])
        self.assertEqual(result["authorization"], "DENY")

    def test_invalid_root_fails_closed(self):
        self.assertFalse(module.verify_export([], module.ZERO)["integrity_valid"])


if __name__ == "__main__":
    unittest.main()
