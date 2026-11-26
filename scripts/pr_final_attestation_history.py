#!/usr/bin/env python3
"""GO-20 v29: complete, independently anchored final-attestation chain verifier.

Verifies every envelope from genesis to pinned latest head, each final report
against its separately provided audit/governance inputs, and cross-signed
custodian rotations. No external trust or storage is established here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_audit_integrity import ZERO, canonical_hash, is_hex, unique_pairs
from pr_final_report_attestation import (TRUST_SCHEMA, check_envelope)
from pr_governance_hardening import validate_shape
from pr_security_acceptance import verify as verify_acceptance

SCHEMA = "palaco.go20-final-attestation-history.v1"
PIN_SCHEMA = "palaco.go20-final-attestation-history-pin.v1"
ROTATION_SCHEMA = "palaco.go20-attestation-key-rotation.v1"
MAX_ENTRIES = 16


def verdict(errors: list[str], checked: int = 0, rotations: int = 0) -> dict:
    return {
        "schema": "palaco.go20-final-attestation-history-verdict.v1",
        "history_valid": not errors,
        "attestations_checked": checked,
        "custodian_rotations_verified": rotations,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def verify_complete_history(history: object, trust: object, external_pin: object) -> dict:
    errors: list[str] = []
    try:
        for value in (history, trust, external_pin):
            validate_shape(value)
    except (ValueError, TypeError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(history, dict) or set(history) != {"schema", "entries", "rotations"} or
            history.get("schema") != SCHEMA or
            not isinstance(history["entries"], list) or
            not 1 <= len(history["entries"]) <= MAX_ENTRIES or
            not isinstance(history["rotations"], list) or
            len(history["rotations"]) > len(history["entries"]) - 1):
        return verdict(["invalid_attestation_history"])
    if (not isinstance(trust, dict) or set(trust) != {"schema", "keys"} or
            trust.get("schema") != TRUST_SCHEMA or
            not isinstance(trust["keys"], dict) or not trust["keys"]):
        return verdict(["invalid_external_custodian_trust"])
    for kid, record in trust["keys"].items():
        if (not isinstance(kid, str) or not kid or
                not isinstance(record, dict) or
                set(record) != {"public_key_hex", "status", "role"} or
                not is_hex(record.get("public_key_hex"), 64) or
                record.get("role") != "attestation_custodian" or
                record.get("status") not in ("active", "revoked")):
            errors.append("invalid_custodian_key_record")
    if (not isinstance(external_pin, dict) or set(external_pin) != {
            "schema", "last_sequence", "last_attestation_sha256", "genesis_attestation_sha256"
    } or external_pin.get("schema") != PIN_SCHEMA or
            type(external_pin.get("last_sequence")) is not int or
            external_pin["last_sequence"] < 0 or
            not is_hex(external_pin.get("last_attestation_sha256"), 64) or
            not is_hex(external_pin.get("genesis_attestation_sha256"), 64)):
        errors.append("invalid_independent_history_pin")
    if errors:
        return verdict(errors)
    entries = history["entries"]
    if external_pin["last_sequence"] != len(entries) - 1:
        errors.append("historical_truncation_or_sequence_rollback")
    seen_rotations: dict[int, dict] = {}
    for i, item in enumerate(history["rotations"]):
        if not isinstance(item, dict) or set(item) != {
            "transition_sequence", "previous_signer_id", "new_signer_id",
            "previous_attestation_sha256", "new_attestation_sha256",
            "old_signature_ed25519_hex", "new_signature_ed25519_hex"
        }:
            errors.append(f"invalid_rotation:{i}")
            continue
        sequence = item["transition_sequence"]
        if type(sequence) is not int or not 1 <= sequence < len(entries) or sequence in seen_rotations:
            errors.append(f"invalid_or_duplicate_rotation_sequence:{i}")
            continue
        seen_rotations[sequence] = item

    # Fail closed before walking potentially corrupted/missing intermediate links.
    if any(not isinstance(e, dict) or set(e) != {"envelope", "report", "inputs"} or
           not isinstance(e.get("envelope"), dict) for e in entries):
        return verdict(errors + ["malformed_historical_entry"])
    previous = ZERO
    verified = 0
    rotations_ok = 0
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"envelope", "report", "inputs"}:
            errors.append(f"invalid_entry:{i}")
            continue
        envelope = entry["envelope"]
        if not isinstance(envelope, dict):
            errors.append(f"invalid_envelope:{i}")
            continue
        errors.extend(f"envelope:{i}:{issue}" for issue in
                      check_envelope(envelope, trust, i, previous))
        report = entry["report"]
        inputs = entry["inputs"]
        try:
            acceptance = verify_acceptance(report, inputs)
            if not acceptance["acceptance_valid"]:
                errors.extend(f"report:{i}:{issue}" for issue in acceptance["errors"])
            if (not isinstance(envelope.get("statement"), dict) or
                    not isinstance(report, dict) or
                    envelope["statement"].get("report_sha256") != report.get("report_sha256")):
                errors.append(f"signed_report_binding_mismatch:{i}")
            # Custodian's public key must not duplicate any controller/reviewer
            # key in the corresponding independently provided evidence.
            signer_id = envelope.get("signer_key_id")
            signer = trust["keys"].get(signer_id) if isinstance(signer_id, str) else None
            forbidden = {
                rec["public_key_hex"]
                for rec in inputs["controller_trust"]["controllers"].values()
                if isinstance(rec, dict) and is_hex(rec.get("public_key_hex"), 64)
            }
            for snapshot in inputs["history"]["snapshots"]:
                forbidden.update(
                    rec["public_key_hex"]
                    for rec in snapshot["reviewer_trust"]["reviewers"].values()
                    if isinstance(rec, dict) and is_hex(rec.get("public_key_hex"), 64)
                )
            if isinstance(signer, dict) and signer.get("public_key_hex") in forbidden:
                errors.append(f"custodian_reviewer_controller_overlap:{i}")
        except (TypeError, ValueError, KeyError, AttributeError, IndexError,
                OverflowError, RecursionError, MemoryError) as exc:
            errors.append(f"malformed_report_evidence:{i}:{type(exc).__name__}")

        if i > 0:
            prev_env = entries[i - 1].get("envelope") if isinstance(entries[i - 1], dict) else None
            prev_id = prev_env.get("signer_key_id") if isinstance(prev_env, dict) else None
            next_id = envelope.get("signer_key_id")
            rotation = seen_rotations.get(i)
            if prev_id == next_id:
                if rotation is not None:
                    errors.append(f"unnecessary_rotation:{i}")
            elif rotation is None:
                errors.append(f"unsigned_custodian_rotation:{i}")
            else:
                prior_key = trust["keys"].get(prev_id) if isinstance(prev_id, str) else None
                next_key = trust["keys"].get(next_id) if isinstance(next_id, str) else None
                if (not isinstance(prior_key, dict) or not isinstance(next_key, dict) or
                        prior_key.get("public_key_hex") == next_key.get("public_key_hex")):
                    errors.append(f"rotation_key_identity_overlap:{i}")
                expected = {
                    "transition_sequence": i,
                    "previous_signer_id": prev_id,
                    "new_signer_id": next_id,
                    "previous_attestation_sha256": canonical_hash(prev_env),
                    "new_attestation_sha256": canonical_hash(envelope),
                }
                if any(rotation.get(k) != v or type(rotation.get(k)) is not type(v)
                       for k, v in expected.items()):
                    errors.append(f"rotation_binding_mismatch:{i}")
                stmt = {"schema": ROTATION_SCHEMA, **expected}
                signatures_good = True
                for name, key in (("old", prior_key), ("new", next_key)):
                    signature = rotation.get(name + "_signature_ed25519_hex")
                    if (not isinstance(key, dict) or key.get("status") != "active" or
                            not is_hex(key.get("public_key_hex"), 64) or
                            not is_hex(signature, 128)):
                        signatures_good = False
                        errors.append(f"invalid_rotation_signer:{i}:{name}")
                        continue
                    issue = verify_signature(key["public_key_hex"], signature, stmt)
                    if issue:
                        signatures_good = False
                        errors.append(f"rotation_signature:{i}:{name}:{issue}")
                if signatures_good and not any(x.startswith(f"rotation_binding_mismatch:{i}") for x in errors):
                    rotations_ok += 1
        try:
            previous = canonical_hash(envelope)
        except (TypeError, ValueError, RecursionError, OverflowError):
            errors.append(f"invalid_envelope_encoding:{i}")
            previous = ZERO
        verified += 1
    if entries and isinstance(entries[0], dict) and isinstance(entries[0].get("envelope"), dict):
        try:
            if canonical_hash(entries[0]["envelope"]) != external_pin["genesis_attestation_sha256"]:
                errors.append("independent_genesis_anchor_mismatch")
        except (TypeError, ValueError, RecursionError, OverflowError):
            errors.append("invalid_genesis_encoding")
    if previous != external_pin["last_attestation_sha256"]:
        errors.append("independent_last_anchor_mismatch")
    return verdict(errors, verified, rotations_ok)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--custodian-trust", type=Path, required=True)
    parser.add_argument("--independent-pin", type=Path, required=True)
    args = parser.parse_args()
    try:
        def read_file(path: Path) -> object:
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("oversize_or_missing_file")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        out = verify_complete_history(
            read_file(args.history), read_file(args.custodian_trust),
            read_file(args.independent_pin))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out["history_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
