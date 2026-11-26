"""Fail-closed trust/revocation/replay tests for GO-20."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("pr_attestation_policy", SCRIPTS / "pr_attestation_policy.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PolicyTests(unittest.TestCase):
    def registry(self, status="active", first=0, last=None):
        return {"schema": module.SCHEMA, "keys": {
            "reviewer": {"public_key_hex": "a" * 64, "status": status,
                         "valid_from_sequence": first, "valid_until_sequence": last}
        }}

    def journal(self, entries=None):
        return {"schema": module.JOURNAL_SCHEMA, "consumed_entry_sha256": entries or []}

    def chain(self):
        return {"schema": "palaco.pr-attestation-chain.v1", "entries": [{
            "sequence": 0, "previous_entry_sha256": "0" * 64,
            "report": {"decision": "HOLD", "authorization": "DENY"},
            "key_id": "reviewer", "signature_ed25519_hex": "0" * 128,
            "entry_sha256": "b" * 64
        }]}

    def test_revoked_signer(self):
        result = module.assess_policy(self.chain(), self.registry("revoked"), self.journal())
        self.assertIn("revoked_signer:0", result["issues"])
        self.assertEqual(result["authorization"], "DENY")

    def test_sequence_scope(self):
        result = module.assess_policy(self.chain(), self.registry(first=1), self.journal())
        self.assertIn("signer_outside_sequence_scope:0", result["issues"])

    def test_replay_journal(self):
        result = module.assess_policy(self.chain(), self.registry(), self.journal(["b" * 64]))
        self.assertIn("replayed_entry:0", result["issues"])

    def test_unknown_signer(self):
        c = self.chain()
        c["entries"][0]["key_id"] = "stranger"
        result = module.assess_policy(c, self.registry(), self.journal())
        self.assertIn("unregistered_signer:0", result["issues"])

    def test_missing_registry(self):
        result = module.assess_policy(self.chain(), None, self.journal())
        self.assertIn("invalid_trust_registry", result["issues"])

    def test_missing_journal(self):
        result = module.assess_policy(self.chain(), self.registry(), None)
        self.assertIn("invalid_replay_journal", result["issues"])

    def test_duplicate_replay_journal_entries(self):
        journal = self.journal(["a" * 64, "a" * 64])
        result = module.assess_policy(self.chain(), self.registry(), journal)
        self.assertIn("invalid_replay_journal", result["issues"])

    def test_malformed_key_record(self):
        registry = self.registry()
        registry["keys"]["reviewer"]["valid_from_sequence"] = True
        result = module.assess_policy(self.chain(), registry, self.journal())
        self.assertIn("invalid_key_record", result["issues"])

    def test_never_grants_authorization(self):
        result = module.assess_policy(self.chain(), self.registry(), self.journal())
        self.assertFalse(result["policy_valid"])
        self.assertEqual((result["decision"], result["authorization"]), ("HOLD", "DENY"))

    def test_signed_valid_chain_still_denies(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("optional cryptography not installed")
        key = Ed25519PrivateKey.generate()
        registry = self.registry()
        registry["keys"]["reviewer"]["public_key_hex"] = key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw).hex()
        chain = self.chain()
        entry = chain["entries"][0]
        report = {"decision": "HOLD", "authorization": "DENY"}
        report["report_sha256"] = module.digest(report)
        entry["report"] = report
        statement = {"schema": "palaco.pr-attestation-statement.v1",
                     "sequence": 0, "previous_entry_sha256": "0" * 64,
                     "report_sha256": report["report_sha256"]}
        entry["signature_ed25519_hex"] = key.sign(bytes.fromhex(module.digest(statement))).hex()
        entry["entry_sha256"] = module.digest({k: v for k, v in entry.items() if k != "entry_sha256"})
        verdict = module.assess_policy(chain, registry, self.journal())
        self.assertTrue(verdict["policy_valid"], verdict["issues"])
        self.assertEqual(verdict["authorization"], "DENY")
        revoked = module.assess_policy(chain, self.registry("revoked"), self.journal())
        self.assertFalse(revoked["policy_valid"])


if __name__ == "__main__":
    unittest.main()
