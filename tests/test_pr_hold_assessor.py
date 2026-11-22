"""Negative and contract tests for the offline PR assessor."""
import importlib.util
import hashlib
import json
import tempfile
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
            "evidence": [{
                "kind": "unit-test-log",
                "head_sha": "a" * 40,
                "artifact_sha256": "b" * 64,
                "path": "proof.txt",
            }],
            "go13_release_authorized": True,
        }

    def test_complete_inputs_still_deny(self):
        result = module.assess(self.valid())
        self.assertFalse(result["technical_inputs_complete"])
        self.assertIn("evidence_not_verified", result["reasons"])
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))

    def test_missing_evidence(self):
        data = self.valid()
        data.pop("evidence")
        self.assertIn("missing_evidence", module.assess(data)["reasons"])

    def test_pending_check(self):
        data = self.valid()
        data["checks"]["lint"] = "pending"
        self.assertIn("check_not_success:lint", module.assess(data)["reasons"])

    def test_go13_missing(self):
        data = self.valid()
        data["go13_release_authorized"] = False
        self.assertIn("go13_not_authorized", module.assess(data)["reasons"])

    def test_malformed_sha(self):
        data = self.valid()
        data["head_sha"] = "bad"
        self.assertIn("invalid_head_sha", module.assess(data)["reasons"])

    def test_invalid_check_state(self):
        data = self.valid()
        data["checks"] = {"test": "unknown"}
        self.assertIn("invalid_check_entry", module.assess(data)["reasons"])

    def test_different_evidence_commit(self):
        data = self.valid()
        data["evidence"][0]["head_sha"] = "c" * 40
        self.assertIn("evidence_head_mismatch", module.assess(data)["reasons"])

    def test_invalid_digest(self):
        data = self.valid()
        data["evidence"][0]["artifact_sha256"] = "bad"
        self.assertIn("invalid_evidence", module.assess(data)["reasons"])

    def test_duplicate_digest(self):
        data = self.valid()
        data["evidence"].append(dict(data["evidence"][0]))
        self.assertIn("duplicate_evidence_digest", module.assess(data)["reasons"])

    def test_reject_duplicate_json_keys(self):
        with self.assertRaises(ValueError):
            json.loads('{"checks": {}, "checks": {}}', object_pairs_hook=module.reject_duplicate_keys)

    def test_unhashable_input(self):
        data = self.valid()
        data["reviews"] = []
        data["checks"]["lint"] = []
        result = module.assess(data)
        self.assertIn("invalid_reviews", result["reasons"])
        self.assertIn("invalid_check_entry", result["reasons"])

    def test_legacy_unbound_evidence_rejected(self):
        data = self.valid()
        data["evidence"] = ["unbound-evidence"]
        self.assertIn("invalid_evidence", module.assess(data)["reasons"])

    def test_verified_file_matches_and_still_denies(self):
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory) / "proof.txt"
            proof.write_bytes(b"synthetic local evidence")
            data = self.valid()
            data["evidence"][0]["artifact_sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()
            result = module.assess(data, Path(directory))
            self.assertTrue(result["technical_inputs_complete"])
            self.assertEqual(result["authorization"], "DENY")

    def test_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "proof.txt").write_bytes(b"tampered")
            result = module.assess(self.valid(), Path(directory))
            self.assertIn("artifact_digest_mismatch", result["reasons"])

    def test_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            data = self.valid()
            data["evidence"][0]["path"] = "../outside.txt"
            self.assertIn("invalid_artifact_path", module.assess(data, Path(directory))["reasons"])

    def test_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            data = self.valid()
            data["evidence"][0]["path"] = "/etc/passwd"
            self.assertIn("invalid_artifact_path", module.assess(data, Path(directory))["reasons"])

    def test_missing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn("artifact_unreadable", module.assess(self.valid(), Path(directory))["reasons"])

    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.txt").write_bytes(b"evidence")
            (root / "proof.txt").symlink_to(root / "target.txt")
            self.assertIn("artifact_unreadable", module.assess(self.valid(), root)["reasons"])

    def test_invalid_root(self):
        self.assertEqual(module.assess([])["authorization"], "DENY")


if __name__ == "__main__":
    unittest.main()
