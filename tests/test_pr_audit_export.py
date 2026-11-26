"""GO-20 v16: audited row-to-chain export and provenance limits."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("pr_audit_export", ROOT / "scripts" / "pr_audit_export.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from pr_audit_integrity import canonical_hash, verify_export


class ExportTests(unittest.TestCase):
    def rows(self):
        return [
            {"id": 1, "operation": "INSERT", "actor_role": "go20test",
             "tenant_role": "go20_alpha", "entry_sha256": "a" * 64},
            {"id": 4, "operation": "UPDATE", "actor_role": "go20test",
             "tenant_role": "go20_beta", "entry_sha256": "b" * 64},
        ]

    def test_valid_export_with_gap_from_rolled_back_sequence(self):
        bundle = mod.build_export(self.rows())
        self.assertEqual(bundle["manifest"]["source_ids"], [1, 4])
        self.assertEqual([e["id"] for e in bundle["export"]["events"]], [1, 2])
        self.assertTrue(verify_export(bundle["export"], bundle["manifest"]["calculated_head_sha256"])["integrity_valid"])
        self.assertEqual(bundle["manifest"]["authorization"], "DENY")
        self.assertFalse(bundle["manifest"]["independently_attested"])

    def test_export_tampering_detected_with_original_anchor(self):
        bundle = mod.build_export(self.rows())
        bundle["export"]["events"][0]["tenant_role"] = "forged"
        self.assertFalse(verify_export(bundle["export"], bundle["manifest"]["calculated_head_sha256"])["integrity_valid"])

    def test_missing_row_rejected_by_manifest_count(self):
        bundle = mod.build_export(self.rows())
        bundle["export"]["events"].pop()
        self.assertNotEqual(len(bundle["export"]["events"]), bundle["manifest"]["event_count"])

    def test_duplicate_source_id_rejected(self):
        rows = self.rows()
        rows[1]["id"] = 1
        with self.assertRaisesRegex(ValueError, "source_id_not_strictly_increasing"):
            mod.build_export(rows)

    def test_out_of_order_source_id_rejected(self):
        rows = self.rows()
        rows.reverse()
        with self.assertRaisesRegex(ValueError, "source_id_not_strictly_increasing"):
            mod.build_export(rows)

    def test_empty_export_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_audit_row_count"):
            mod.build_export([])

    def test_malformed_digest_rejected(self):
        rows = self.rows()
        rows[0]["entry_sha256"] = "bad"
        with self.assertRaisesRegex(ValueError, "invalid_source_row_fields"):
            mod.build_export(rows)

    def test_unknown_source_key_rejected(self):
        rows = self.rows()
        rows[0]["unexpected"] = "x"
        with self.assertRaisesRegex(ValueError, "invalid_source_row"):
            mod.build_export(rows)

    def test_duplicate_json_fields_rejected(self):
        with self.assertRaises(ValueError):
            mod.read_rows('{"id":1,"id":2}\n')

    def test_blank_json_line_rejected(self):
        with self.assertRaisesRegex(ValueError, "blank_row"):
            mod.read_rows(json.dumps(self.rows()[0]) + "\n\n")

    def test_export_manifest_digest_tracks_payload(self):
        bundle = mod.build_export(self.rows())
        self.assertEqual(bundle["manifest"]["export_sha256"], canonical_hash(bundle["export"]))

    def test_large_input_rejected(self):
        with self.assertRaisesRegex(ValueError, "audit_input_too_large"):
            mod.read_rows("x" * (8 * 1024 * 1024 + 1))


if __name__ == "__main__":
    unittest.main()
