#!/usr/bin/env python3
"""GO-20 v24: read-only reviewer governance and release-prohibition gate.

This checks independently provided governance metadata, NOT true real-world
non-collusion. No network actions, signing, approval, merge, or deployment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_assessment_receipt import read_json
from pr_signed_assessment_review import verify_review

SCHEMA = "palaco.go20-reviewer-governance.v1"
PIN_SCHEMA = "palaco.go20-governance-policy-pin.v1"
ROLES = ("evidence_reviewer", "security_reviewer")
PROHIBITIONS = (
    "release", "merge", "deploy", "production_write",
    "policy_override", "self_approval",
)


def verdict(errors: list[str], review_valid: bool = False) -> dict:
    return {
        "schema": "palaco.go20-reviewer-governance-verdict.v1",
        "governance_valid": not errors,
        "review_valid": review_valid,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess_governance(envelope: object, receipt: object, inputs: object,
                      reviewer_trust: object, policy: object, external_pin: object) -> dict:
    review = verify_review(envelope, receipt, inputs, reviewer_trust)
    errors = ["review:" + err for err in review["errors"]]
    if not isinstance(policy, dict) or set(policy) != {
        "schema", "revision", "repository", "reviewers",
        "prohibited_capabilities", "declared_conflicts"
    } or policy.get("schema") != SCHEMA:
        return verdict(errors + ["invalid_policy"], review["review_valid"])
    if not isinstance(external_pin, dict) or set(external_pin) != {
        "schema", "minimum_revision", "policy_sha256"
    } or external_pin.get("schema") != PIN_SCHEMA:
        return verdict(errors + ["invalid_independent_policy_pin"], review["review_valid"])
    if (type(external_pin["minimum_revision"]) is not int or
            external_pin["minimum_revision"] < 0 or
            not is_hex(external_pin["policy_sha256"], 64)):
        return verdict(errors + ["invalid_policy_pin_fields"], review["review_valid"])
    if (type(policy["revision"]) is not int or
            policy["revision"] < external_pin["minimum_revision"]):
        errors.append("policy_rollback")
    if policy["repository"] != "Maurits-pixe/PALACO":
        errors.append("policy_repository_mismatch")
    if canonical_hash(policy) != external_pin["policy_sha256"]:
        errors.append("policy_pin_mismatch")
    if (not isinstance(policy["prohibited_capabilities"], list) or
            set(policy["prohibited_capabilities"]) != set(PROHIBITIONS) or
            len(policy["prohibited_capabilities"]) != len(PROHIBITIONS)):
        errors.append("release_prohibition_incomplete")
    roster = policy["reviewers"]
    if not isinstance(roster, dict) or set(roster) != set(ROLES):
        errors.append("reviewer_roster_incomplete")
        roster = {}
    selected = []
    for role in ROLES:
        record = roster.get(role)
        if not isinstance(record, dict) or set(record) != {
            "reviewer_id", "organization_id", "control_domain_id",
            "conflict_disclosed", "governance_status"
        }:
            errors.append(f"invalid_roster_entry:{role}")
            continue
        if (not all(isinstance(record.get(key), str) and record[key] for key in (
                "reviewer_id", "organization_id", "control_domain_id")) or
                record["conflict_disclosed"] is not False or
                record["governance_status"] != "active"):
            errors.append(f"reviewer_conflict_or_inactive:{role}")
        selected.append(record)
    if len(selected) == 2:
        if selected[0]["reviewer_id"] == selected[1]["reviewer_id"]:
            errors.append("reviewer_identity_overlap")
        if selected[0]["organization_id"] == selected[1]["organization_id"]:
            errors.append("organization_control_overlap")
        if selected[0]["control_domain_id"] == selected[1]["control_domain_id"]:
            errors.append("key_control_domain_overlap")
    if policy["declared_conflicts"] != []:
        errors.append("declared_conflict_present")
    if isinstance(envelope, dict) and isinstance(envelope.get("attestations"), list):
        by_role = {
            att.get("role"): att.get("reviewer_id")
            for att in envelope["attestations"] if isinstance(att, dict)
        }
        for role in ROLES:
            if role in roster and isinstance(roster[role], dict) and (
                by_role.get(role) != roster[role].get("reviewer_id")
            ):
                errors.append(f"roster_attestation_mismatch:{role}")
    return verdict(errors, review["review_valid"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("review", "receipt", "inputs", "reviewer-trust", "policy", "independent-policy-pin"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    try:
        def load(path):
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs)
        out = assess_governance(
            load(args.review), read_json(args.receipt), read_json(args.inputs),
            load(args.reviewer_trust), load(args.policy),
            load(args.independent_policy_pin))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out["governance_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
