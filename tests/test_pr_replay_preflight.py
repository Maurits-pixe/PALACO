"""GO-20 v7 signed state binding and replay preflight regressions."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("pr_replay_preflight", SCRIPTS / "pr_replay_preflight.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReplayPreflightTests(unittest.TestCase):
    def payload(self):
        return {
            "schema": module.SCHEMA,
            "revision": 4,
            "registry": {"schema": "palaco.pr-trust-registry.v1", "keys": {
                "reviewer": {"public_key_hex": "a" * 64, "status": "active",
                             "valid_from_sequence": 0, "valid_until_sequence": None}}},
            "journal": {"schema": "palaco.pr-replay-journal.v1", "consumed_entry_sha256": []},
        }

    def envelope(self):
        return {"payload": self.payload(), "signature_ed25519_hex": "0" * 128}

    def assert_denied(self, verdict):
        self.assertEqual(verdict["authorization"], "DENY")
        self.assertEqual(verdict["decision"], "HOLD")

    def test_revision_conflict(self):
        verdict = module.plan_replay({}, self.envelope(), "a" * 64, 3)
        self.assertIn("revision_mismatch", verdict["errors"])
        self.assertIsNone(verdict["proposal"])
        self.assert_denied(verdict)

    def test_invalid_root(self):
        verdict = module.plan_replay({}, self.envelope(), "bad", 4)
        self.assertIn("invalid_pinned_root", verdict["errors"])
        self.assert_denied(verdict)

    def test_missing_envelope(self):
        verdict = module.plan_replay({}, None, "a" * 64, 4)
        self.assertIn("invalid_snapshot_envelope", verdict["errors"])
        self.assert_denied(verdict)

    def test_invalid_signature(self):
        envelope = self.envelope()
        envelope["signature_ed25519_hex"] = "bad"
        verdict = module.plan_replay({}, envelope, "a" * 64, 4)
        self.assertIn("invalid_snapshot_signature", verdict["errors"])
        self.assert_denied(verdict)

    def test_signed_state_and_valid_chain_still_deny(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("cryptography is not available")
        root = Ed25519PrivateKey.generate()
        reviewer = Ed25519PrivateKey.generate()
        public_root = root.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        public_reviewer = reviewer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        envelope = self.envelope()
        envelope["payload"]["registry"]["keys"]["reviewer"]["public_key_hex"] = public_reviewer
        statement = {"schema": "palaco.pr-state-signature.v1",
                     "payload_sha256": module.digest(envelope["payload"])}
        envelope["signature_ed25519_hex"] = root.sign(bytes.fromhex(module.digest(statement))).hex()
        report = {"decision": "HOLD", "authorization": "DENY"}
        report["report_sha256"] = module.digest(report)
        entry = {"sequence": 0, "previous_entry_sha256": "0" * 64,
                 "report": report, "key_id": "reviewer"}
        statement = {"schema": "palaco.pr-attestation-statement.v1",
                     "sequence": 0, "previous_entry_sha256": "0" * 64,
                     "report_sha256": report["report_sha256"]}
        entry["signature_ed25519_hex"] = reviewer.sign(bytes.fromhex(module.digest(statement))).hex()
        entry["entry_sha256"] = module.digest(entry)
        chain = {"schema": "palaco.pr-attestation-chain.v1", "entries": [entry]}
        result = module.plan_replay(chain, envelope, public_root, 4)
        self.assertTrue(result["technical_preflight_valid"], result["errors"])
        self.assertEqual(result["proposal"]["expected_revision"], 4)
        self.assertFalse(result["proposal"]["atomic_commit_performed"])
        self.assert_denied(result)
        changed = module.plan_replay(chain, envelope, public_root, 5)
        self.assertFalse(changed["technical_preflight_valid"])
        self.assertIsNone(changed["proposal"])
        tampered = self.envelope()
        tampered["payload"]["registry"]["keys"]["reviewer"]["public_key_hex"] = public_reviewer
        tampered["signature_ed25519_hex"] = envelope["signature_ed25519_hex"]
        tampered["payload"]["revision"] = 5
        rejected = module.plan_replay(chain, tampered, public_root, 5)
        self.assertFalse(rejected["technical_preflight_valid"])
        self.assert_denied(rejected)


if __name__ == "__main__":
    unittest.main()
