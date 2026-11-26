"""GO-20 v21: integrated multi-round assessment negative regressions."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pr_audit_export import build_export
from pr_audit_integrity import ZERO, canonical_hash
from pr_multiround_assessor import BASELINE_SCHEMA, SCHEMA, assess
from pr_signed_audit_checkpoint import CHECKPOINT_SCHEMA, TRUST_SCHEMA
from pr_witness_transparency import ENTRY_SCHEMA, PIN_SCHEMA, SCHEMA as LOG_SCHEMA
from pr_audit_witness_forks import TRUST_SCHEMA as WITNESS_TRUST_SCHEMA


class MalformedInputTests(unittest.TestCase):
    def test_missing_roundbook_denied(self):
        v = assess(None, None, None, None, None, None)
        self.assertIn("invalid_roundbook", v["errors"])
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))

    def test_missing_baseline_denied(self):
        v = assess({"schema": SCHEMA, "rounds": [{}, {}]}, None, None, None, None, None)
        self.assertIn("invalid_external_baseline", v["errors"])


class MultiRoundTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("cryptography backend unavailable")
        self.audit_private = Ed25519PrivateKey.generate()
        self.witness_private = {
            name: Ed25519PrivateKey.generate() for name in ("w1", "w2")
        }
        def public(key):
            return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        self.audit_trust = {"schema": TRUST_SCHEMA, "keys": {
            "root": {"public_key_hex": public(self.audit_private), "status": "active"}
        }}
        self.witness_trust = {"schema": WITNESS_TRUST_SCHEMA, "keys": {
            name: {"public_key_hex": public(key), "status": "active"}
            for name, key in self.witness_private.items()
        }}
        self.rows = [
            {"id": index, "operation": "INSERT", "actor_role": "test",
             "tenant_role": "go20_alpha", "entry_sha256": f"{index:x}" * 64}
            for index in range(1, 5)
        ]
        self.first_revision = 50
        self.rounds = [
            self.make_bundle(self.rows[:2], 50),
            self.make_bundle(self.rows[:3], 51),
            self.make_bundle(self.rows[:4], 52),
        ]
        self.roundbook = {"schema": SCHEMA, "rounds": self.rounds}
        self.hashes = [canonical_hash(r["checkpoint"]["payload"]) for r in self.rounds]
        self.baseline = {
            "schema": BASELINE_SCHEMA, "first_revision": 50,
            "first_payload_sha256": self.hashes[0],
            "last_revision": 52,
            "last_payload_sha256": self.hashes[-1],
        }
        self.logbook = {"schema": LOG_SCHEMA, "logs": [
            self.make_log(name, self.hashes) for name in ("w1", "w2")
        ]}
        self.pins = {"schema": PIN_SCHEMA, "witnesses": {
            log["witness_id"]: {
                "last_sequence": len(log["entries"]),
                "head_sha256": log["entries"][-1]["entry_sha256"],
            } for log in self.logbook["logs"]
        }}

    def make_bundle(self, rows, revision):
        contents = build_export(copy.deepcopy(rows))
        m = contents["manifest"]
        payload = {
            "schema": CHECKPOINT_SCHEMA, "revision": revision,
            "repository": "Maurits-pixe/PALACO",
            "export_sha256": m["export_sha256"],
            "head_sha256": m["calculated_head_sha256"],
            "event_count": m["event_count"],
            "source_ids_sha256": canonical_hash(m["source_ids"]),
            "first_source_id": m["source_ids"][0],
            "last_source_id": m["source_ids"][-1],
        }
        stmt = {"schema": "palaco.go20-audit-checkpoint-signature.v1",
                "payload_sha256": canonical_hash(payload)}
        signature = self.audit_private.sign(bytes.fromhex(canonical_hash(stmt))).hex()
        return {"export": contents["export"], "manifest": m,
                "checkpoint": {"payload": payload, "signer_key_id": "root",
                               "signature_ed25519_hex": signature}}

    def make_log(self, wid, hashes):
        out = []
        previous = ZERO
        for sequence, digest in enumerate(hashes, 1):
            statement = {
                "schema": ENTRY_SCHEMA, "witness_id": wid, "sequence": sequence,
                "revision": self.first_revision + sequence - 1,
                "checkpoint_payload_sha256": digest,
                "previous_entry_sha256": previous,
            }
            h = canonical_hash(statement)
            out.append({
                "sequence": sequence, "revision": statement["revision"],
                "checkpoint_payload_sha256": digest,
                "previous_entry_sha256": previous, "entry_sha256": h,
                "signature_ed25519_hex": self.witness_private[wid].sign(bytes.fromhex(h)).hex(),
            })
            previous = h
        return {"witness_id": wid, "entries": out}

    def check(self):
        return assess(self.roundbook, self.audit_trust, self.witness_trust,
                      self.logbook, self.pins, self.baseline)

    def test_three_rounds_valid_but_no_authority(self):
        v = self.check()
        self.assertTrue(v["technical_evidence_valid"], v["errors"])
        self.assertEqual(v["rounds_checked"], 3)
        self.assertEqual((v["decision"], v["authorization"]), ("HOLD", "DENY"))
        self.assertFalse(v["production_commit_performed"])

    def test_baseline_first_hash_substitution(self):
        self.baseline["first_payload_sha256"] = ZERO
        self.assertIn("independent_first_checkpoint_mismatch", self.check()["errors"])

    def test_baseline_last_hash_substitution(self):
        self.baseline["last_payload_sha256"] = ZERO
        self.assertIn("independent_last_checkpoint_mismatch", self.check()["errors"])

    def test_rollback_floor_rejected(self):
        self.baseline["last_revision"] = 51
        self.assertIn("invalid_external_baseline_fields", self.check()["errors"])

    def test_middle_round_historical_rewrite(self):
        rewritten = copy.deepcopy(self.rows[:3])
        rewritten[0]["tenant_role"] = "go20_beta"
        self.rounds[1] = self.make_bundle(rewritten, 51)
        v = self.check()
        self.assertFalse(v["technical_evidence_valid"])
        self.assertTrue(any("historical_events_modified_or_missing" in x for x in v["errors"]))

    def test_missing_middle_round_rejected(self):
        self.roundbook["rounds"].pop(1)
        self.assertIn("invalid_external_baseline_fields", self.check()["errors"])

    def test_published_digest_does_not_match_checkpoint(self):
        self.logbook["logs"][1] = self.make_log("w2", [self.hashes[0], ZERO, self.hashes[-1]])
        self.pins["witnesses"]["w2"]["head_sha256"] = self.logbook["logs"][1]["entries"][-1]["entry_sha256"]
        v = self.check()
        self.assertTrue(any(x.startswith("transparency:conflicting_signed_publications") for x in v["errors"]))

    def test_revoked_witness_is_not_valid(self):
        self.witness_trust["keys"]["w1"]["status"] = "revoked"
        self.assertIn("transparency:untrusted_or_revoked_witness:w1", self.check()["errors"])

    def test_invalid_signature_rejected(self):
        self.rounds[1]["checkpoint"]["signature_ed25519_hex"] = "0" * 128
        self.assertFalse(self.check()["technical_evidence_valid"])

    def test_witness_pin_rollback(self):
        self.pins["witnesses"]["w1"]["last_sequence"] = 2
        self.assertIn("transparency:independent_head_mismatch:w1", self.check()["errors"])

    def test_publication_round_missing(self):
        self.logbook["logs"][0] = self.make_log("w1", self.hashes[:2])
        self.pins["witnesses"]["w1"]["last_sequence"] = 2
        self.pins["witnesses"]["w1"]["head_sha256"] = self.logbook["logs"][0]["entries"][-1]["entry_sha256"]
        self.assertFalse(self.check()["technical_evidence_valid"])


if __name__ == "__main__":
    unittest.main()
