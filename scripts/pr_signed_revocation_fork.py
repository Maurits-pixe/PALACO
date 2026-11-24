#!/usr/bin/env python3
"""GO-20 v44: independently signed revocations and historical fork comparison.

Two v43 histories are checked independently, then cross-compared to detect
forks even if an attacker supplies a new otherwise coherent branch pin.
An external Ed25519 signer authenticates the revocation register and a
separately retained anchor fixes the expected canonical history head.
Verification only; no fencing, promotion, network or production writes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_fencing_quorum_history import verify_history

SCHEMA = "palaco.go20-signed-revocation-fork-evidence.v1"
PIN_SCHEMA = "palaco.go20-signed-revocation-fork-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-revocation-register-statement.v1"


def verdict(errors: list[str], histories: int = 0, epochs: int = 0) -> dict:
    return {
        "schema": "palaco.go20-revocation-fork-verdict.v1",
        "historical_evidence_valid": not errors,
        "histories_verified": histories,
        "epochs_verified": epochs,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "fence_performed": False,
        "failover_authorized": False,
        "promotion_performed": False,
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def check(left_history, left_pin, right_history, right_pin,
          revocations, signed_register, independent_pin) -> dict:
    try:
        for value in (left_history, left_pin, right_history, right_pin,
                      revocations, signed_register, independent_pin):
            validate_shape(value)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(signed_register, dict) or set(signed_register) != {
            "schema", "key_id", "signature_ed25519_hex"
    } or signed_register.get("schema") != SCHEMA or
            not isinstance(signed_register.get("key_id"), str) or
            not signed_register["key_id"] or
            not is_hex(signed_register.get("signature_ed25519_hex"), 128)):
        return verdict(["invalid_signed_revocation_register"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "trusted_key_id", "trusted_public_key_hex",
            "revocations_sha256", "history_sha256", "minimum_epoch"
    } or independent_pin.get("schema") != PIN_SCHEMA or
            not isinstance(independent_pin.get("trusted_key_id"), str) or
            not independent_pin["trusted_key_id"] or
            not is_hex(independent_pin.get("trusted_public_key_hex"), 64) or
            not is_hex(independent_pin.get("revocations_sha256"), 64) or
            not is_hex(independent_pin.get("history_sha256"), 64) or
            type(independent_pin.get("minimum_epoch")) is not int or
            independent_pin["minimum_epoch"] < 0):
        return verdict(["invalid_independent_revocation_pin"])
    if signed_register["key_id"] != independent_pin["trusted_key_id"]:
        return verdict(["revocation_signer_identity_mismatch"])
    if canonical_hash(revocations) != independent_pin["revocations_sha256"]:
        return verdict(["independent_revocation_mismatch"])
    statement = {
        "schema": STATEMENT_SCHEMA,
        "repository": "Maurits-pixe/PALACO",
        "revocations_sha256": independent_pin["revocations_sha256"],
        "minimum_epoch": independent_pin["minimum_epoch"],
        "history_sha256": independent_pin["history_sha256"],
        "decision": "HOLD",
        "authorization": "DENY",
    }
    issue = verify_signature(
        independent_pin["trusted_public_key_hex"],
        signed_register["signature_ed25519_hex"], statement)
    if issue:
        return verdict(["invalid_revocation_signature:" + issue])
    results = []
    for label, history, pin in (
            ("left", left_history, left_pin),
            ("right", right_history, right_pin)):
        try:
            validated = verify_history(history, pin, revocations)
        except (TypeError, ValueError, KeyError, IndexError, AttributeError,
                RecursionError, OverflowError, MemoryError) as exc:
            return verdict([f"malformed_{label}_history:" + type(exc).__name__])
        if not validated["history_valid"]:
            return verdict([f"{label}:" + e for e in validated["errors"]])
        results.append(validated)
    errors = []
    if (not isinstance(left_pin, dict) or not isinstance(right_pin, dict) or
            left_pin["first_epoch"] != right_pin["first_epoch"] or
            left_pin["last_epoch"] != right_pin["last_epoch"]):
        errors.append("fork_epoch_range_mismatch")
    elif left_pin["last_epoch"] < independent_pin["minimum_epoch"]:
        errors.append("history_epoch_rollback")
    left_hash = canonical_hash(left_history)
    right_hash = canonical_hash(right_history)
    if left_hash != right_hash:
        errors.append("historical_fork_detected")
    if left_hash != independent_pin["history_sha256"]:
        errors.append("left_history_external_anchor_mismatch")
    if right_hash != independent_pin["history_sha256"]:
        errors.append("right_history_external_anchor_mismatch")
    return verdict(errors, 2, min(r["epochs_verified"] for r in results))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("left-history", "left-pin", "right-history", "right-pin",
                 "revocations", "signed-register", "independent-pin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_input")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = check(*(read(getattr(args, name.replace("-", "_"))) for name in (
            "left-history", "left-pin", "right-history", "right-pin",
            "revocations", "signed-register", "independent-pin")))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            IndexError, OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out["historical_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
