#!/usr/bin/env python3
"""GO-20 v18: read-only consecutive signed audit checkpoint verifier.

Both snapshots must have valid v17 Ed25519 signatures. A prior checkpoint
digest/revision MUST be supplied through an independently retained witness.
No state writes, no authorization, no witness storage or signing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, unique_pairs
from pr_signed_audit_checkpoint import verify_checkpoint

WITNESS_SCHEMA = "palaco.go20-audit-prior-witness.v1"


def verify_continuity(previous: object, current: object, trust: object,
                      external_witness: object) -> dict:
    errors: list[str] = []
    if not isinstance(external_witness, dict) or set(external_witness) != {
        "schema", "revision", "checkpoint_payload_sha256"
    } or external_witness.get("schema") != WITNESS_SCHEMA:
        return verdict(["invalid_independent_witness"])
    expected_revision = external_witness["revision"]
    expected_hash = external_witness["checkpoint_payload_sha256"]
    if (type(expected_revision) is not int or expected_revision < 0 or
            not isinstance(expected_hash, str) or len(expected_hash) != 64 or
            any(c not in "0123456789abcdef" for c in expected_hash)):
        return verdict(["invalid_independent_witness"])
    if not isinstance(previous, dict) or set(previous) != {"export", "manifest", "checkpoint"}:
        return verdict(["invalid_previous_bundle"])
    if not isinstance(current, dict) or set(current) != {"export", "manifest", "checkpoint"}:
        return verdict(["invalid_current_bundle"])

    prior_cp = previous["checkpoint"]
    latest_cp = current["checkpoint"]
    prior_payload = prior_cp.get("payload") if isinstance(prior_cp, dict) else None
    latest_payload = latest_cp.get("payload") if isinstance(latest_cp, dict) else None
    if not isinstance(prior_payload, dict) or not isinstance(latest_payload, dict):
        return verdict(["invalid_checkpoint_payload"])
    try:
        if canonical_hash(prior_payload) != expected_hash:
            errors.append("independent_witness_hash_mismatch")
    except (TypeError, ValueError, RecursionError, OverflowError):
        errors.append("invalid_checkpoint_encoding")
    if type(prior_payload.get("revision")) is not int or prior_payload.get("revision") != expected_revision:
        errors.append("independent_witness_revision_mismatch")

    prior_verdict = verify_checkpoint(previous["export"], previous["manifest"],
                                     prior_cp, trust, expected_revision)
    current_verdict = verify_checkpoint(current["export"], current["manifest"],
                                       latest_cp, trust, expected_revision + 1)
    if not prior_verdict["checkpoint_valid"]:
        errors.extend("previous:" + error for error in prior_verdict["errors"])
    if not current_verdict["checkpoint_valid"]:
        errors.extend("current:" + error for error in current_verdict["errors"])
    if errors:
        return verdict(errors)

    # The checkpoint describes a full cumulative ledger, NOT a delta.
    prior_events = previous["export"]["events"]
    latest_events = current["export"]["events"]
    prior_ids = previous["manifest"]["source_ids"]
    latest_ids = current["manifest"]["source_ids"]
    if (latest_payload["revision"] != expected_revision + 1 or
            latest_payload["event_count"] <= prior_payload["event_count"]):
        errors.append("checkpoint_progression_mismatch")
    if len(latest_events) <= len(prior_events) or latest_events[:len(prior_events)] != prior_events:
        errors.append("historical_events_modified_or_missing")
    if len(latest_ids) <= len(prior_ids) or latest_ids[:len(prior_ids)] != prior_ids:
        errors.append("historical_source_ids_modified_or_missing")
    if (latest_payload["first_source_id"] != prior_payload["first_source_id"] or
            latest_payload["last_source_id"] <= prior_payload["last_source_id"]):
        errors.append("source_boundary_rollback")
    return verdict(errors)


def verdict(errors: list[str]) -> dict:
    return {
        "schema": "palaco.go20-checkpoint-continuity-verdict.v1",
        "continuity_valid": not errors,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "note": "Witness must be independently retained; no trust establishment or persistence provided.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-bundle", type=Path, required=True)
    parser.add_argument("--current-bundle", type=Path, required=True)
    parser.add_argument("--trusted-keys", type=Path, required=True)
    parser.add_argument("--independent-witness", type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path: Path):
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        result = verify_continuity(read(args.previous_bundle), read(args.current_bundle),
                                   read(args.trusted_keys), read(args.independent_witness))
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["continuity_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
