"""PALACO independent attestation-chain contract and negative tests."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pr_attestation_chain.py"
spec = importlib.util.spec_from_file_location("pr_attestation_chain", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ChainTests(unittest.TestCase):
    def fixture(self):
        report = {
            "schema": "palaco.pr-assessment.v2",
            "decision": "HOLD",
            "authorization": "DENY",
            "reasons": [],
            "technical_inputs_complete": True,
            "manifest_sha256": "a" * 64,
            "snapshot_sha256": "b" * 64,
        }
        report["report_sha256"] = module.digest(report)
        entry = {
            "sequence": 0, "previous_entry_sha256": module.ZERO,
            "report": report, "key_id": "external-reviewer",
            "signature_ed25519_hex": "0" * 128,
        }
        entry["entry_sha256"] = module.digest(entry)
        return {"schema": module.SCHEMA, "entries": [entry]}

    def test_no_trusted_keys_fails_closed(self):
        result = module.assess_chain(self.fixture(), {})
        self.assertFalse(result["chain_valid"])
        self.assertIn("invalid_external_trust_store", result["errors"])
        self.assertEqual(result["authorization"], "DENY")

    def test_unknown_signer_rejected(self):
        result = module.assess_chain(self.fixture(), {"other": "a" * 64})
        self.assertIn("unknown_signer:0", result["errors"])

    def test_report_tampering_rejected(self):
        chain = self.fixture()
        chain["entries"][0]["report"]["reasons"] = ["modified"]
        result = module.assess_chain(chain, {"other": "a" * 64})
        self.assertIn("report_digest_mismatch:0", result["errors"])

    def test_wrong_link_rejected(self):
        chain = self.fixture()
        chain["entries"][0]["previous_entry_sha256"] = "f" * 64
        result = module.assess_chain(chain, {"other": "a" * 64})
        self.assertIn("chain_link_mismatch:0", result["errors"])

    def test_sequence_gap_rejected(self):
        chain = self.fixture()
        chain["entries"][0]["sequence"] = 3
        result = module.assess_chain(chain, {"other": "a" * 64})
        self.assertIn("sequence_mismatch:0", result["errors"])

    def test_entry_digest_rejected(self):
        chain = self.fixture()
        chain["entries"][0]["entry_sha256"] = "1" * 64
        result = module.assess_chain(chain, {"other": "a" * 64})
        self.assertIn("entry_digest_mismatch:0", result["errors"])

    def test_empty_chain_rejected(self):
        result = module.assess_chain({"schema": module.SCHEMA, "entries": []}, {"x": "a" * 64})
        self.assertIn("invalid_chain_length", result["errors"])

    def test_unknown_state_never_authorized(self):
        chain = self.fixture()
        chain["entries"][0]["report"]["authorization"] = "ALLOW"
        result = module.assess_chain(chain, {"other": "a" * 64})
        self.assertIn("unauthorized_report_state:0", result["errors"])
        self.assertEqual(result["authorization"], "DENY")

    def test_duplicate_json_fields_rejected(self):
        import json
        with self.assertRaises(ValueError):
            json.loads('{"entries":[],"entries":[]}', object_pairs_hook=module.unique_pairs)

    def test_real_signed_chain_when_crypto_available(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("optional cryptography dependency not installed")
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        chain = self.fixture()
        entry = chain["entries"][0]
        statement = {
            "schema": "palaco.pr-attestation-statement.v1",
            "sequence": 0,
            "previous_entry_sha256": module.ZERO,
            "report_sha256": entry["report"]["report_sha256"],
        }
        entry["signature_ed25519_hex"] = private.sign(bytes.fromhex(module.digest(statement))).hex()
        entry["entry_sha256"] = module.digest({
            key: value for key, value in entry.items() if key != "entry_sha256"
        })
        result = module.assess_chain(chain, {"external-reviewer": public})
        self.assertTrue(result["chain_valid"], result["errors"])
        self.assertEqual(result["decision"], "HOLD")
        self.assertEqual(result["authorization"], "DENY")
        entry["signature_ed25519_hex"] = "0" * 128
        entry["entry_sha256"] = module.digest({
            key: value for key, value in entry.items() if key != "entry_sha256"
        })
        self.assertIn("signature_invalid:0", module.assess_chain(chain, {"external-reviewer": public})["errors"])


if __name__ == "__main__":
    unittest.main()
