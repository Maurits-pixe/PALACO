#!/usr/bin/env python3
"""GO-20 v23: read-only dual-role signed receipt review.

Two independent active reviewer public keys must sign the exact same receipt.
Never issues review signatures or authorizes merges, deployments or execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_assessment_receipt import read_json, verify_receipt

SCHEMA = "palaco.go20-signed-assessment-review.v1"
TRUST_SCHEMA = "palaco.go20-reviewer-role-trust.v1"
STATEMENT_SCHEMA = "palaco.go20-reviewer-attestation.v1"
ROLES = ("evidence_reviewer", "security_reviewer")


def verdict(errors: list[str], reviewed: int = 0) -> dict:
    return {
        "schema": "palaco.go20-signed-assessment-verdict.v1",
        "review_valid": not errors,
        "reviewer_roles_verified": reviewed,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "release_authorized": False,
        "production_commit_performed": False,
    }


def verify_review(envelope: object, receipt: object, inputs: object,
                  reviewer_trust: object) -> dict:
    errors: list[str] = []
    if (not isinstance(envelope, dict) or
            set(envelope) != {"schema", "receipt_sha256", "attestations"} or
            envelope.get("schema") != SCHEMA or
            not isinstance(envelope.get("attestations"), list) or
            len(envelope["attestations"]) != 2):
        return verdict(["invalid_review_envelope"])
    if (not isinstance(reviewer_trust, dict) or
            set(reviewer_trust) != {"schema", "reviewers"} or
            reviewer_trust.get("schema") != TRUST_SCHEMA or
            not isinstance(reviewer_trust.get("reviewers"), dict)):
        return verdict(["invalid_reviewer_trust"])
    if (not isinstance(receipt, dict) or
            not is_hex(receipt.get("receipt_sha256"), 64) or
            envelope["receipt_sha256"] != receipt["receipt_sha256"]):
        errors.append("receipt_binding_mismatch")
    receipt_result = verify_receipt(receipt, inputs)
    if not receipt_result["receipt_valid"]:
        errors.extend("receipt:" + issue for issue in receipt_result["errors"])
    reviewers = reviewer_trust["reviewers"]
    selected: dict[str, str] = {}
    selected_keys: set[str] = set()
    for index, item in enumerate(envelope["attestations"]):
        if not isinstance(item, dict) or set(item) != {
            "role", "reviewer_id", "signature_ed25519_hex"
        }:
            errors.append(f"invalid_attestation:{index}")
            continue
        role, reviewer_id = item["role"], item["reviewer_id"]
        if role not in ROLES or role in selected:
            errors.append(f"invalid_or_duplicate_role:{index}")
            continue
        if not isinstance(reviewer_id, str) or reviewer_id in selected.values():
            errors.append(f"reviewer_separation_failed:{index}")
            continue
        selected[role] = reviewer_id
        record = reviewers.get(reviewer_id)
        if (not isinstance(record, dict) or
                set(record) != {"public_key_hex", "status", "role"} or
                not is_hex(record.get("public_key_hex"), 64) or
                record.get("status") != "active" or
                record.get("role") != role):
            errors.append(f"untrusted_revoked_or_wrong_role:{index}")
            continue
        if record["public_key_hex"] in selected_keys:
            errors.append(f"reviewer_public_key_reuse:{index}")
            continue
        selected_keys.add(record["public_key_hex"])
        if not is_hex(item["signature_ed25519_hex"], 128):
            errors.append(f"invalid_signature_encoding:{index}")
            continue
        statement = {
            "schema": STATEMENT_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "receipt_sha256": envelope["receipt_sha256"],
            "role": role,
            "reviewer_id": reviewer_id,
            "decision": "HOLD",
            "authorization": "DENY",
        }
        issue = verify_signature(record["public_key_hex"],
                                 item["signature_ed25519_hex"], statement)
        if issue:
            errors.append(f"signature:{index}:{issue}")
    if set(selected) != set(ROLES):
        errors.append("reviewer_role_coverage_incomplete")
    return verdict(errors, len(selected))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--reviewer-trust", type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path: Path):
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs)
        out = verify_review(read(args.review), read_json(args.receipt),
                            read_json(args.inputs), read(args.reviewer_trust))
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError,
            RecursionError, KeyError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["review_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
