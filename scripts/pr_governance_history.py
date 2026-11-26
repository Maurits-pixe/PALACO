#!/usr/bin/env python3
"""GO-20 v25: read-only, signed reviewer-policy history verifier.

Each historical snapshot is re-verified by v24; policy transitions must
be signed by a separately provisioned active governance controller.
Independently anchored endpoints are required. This does not govern a
real organization or authorize release.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_assessment_receipt import read_json
from pr_review_governance import assess_governance, ROLES, PROHIBITIONS

SCHEMA = "palaco.go20-governance-history.v1"
PIN_SCHEMA = "palaco.go20-governance-history-pin.v1"
CONTROLLER_TRUST_SCHEMA = "palaco.go20-governance-controller-trust.v1"
TRANSITION_SCHEMA = "palaco.go20-governance-transition.v1"
MAX_VERSIONS = 16


def report(errors: list[str], checked: int = 0, changes: int = 0) -> dict:
    return {
        "schema": "palaco.go20-governance-history-verdict.v1",
        "history_valid": not errors,
        "versions_checked": checked,
        "reviewer_rotations_verified": changes,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def verify_history(history: object, anchor: object, controller_trust: object) -> dict:
    errors: list[str] = []
    if (not isinstance(history, dict) or set(history) != {"schema", "snapshots", "transitions"} or
            history.get("schema") != SCHEMA or not isinstance(history.get("snapshots"), list) or
            not 2 <= len(history["snapshots"]) <= MAX_VERSIONS or
            not isinstance(history.get("transitions"), list) or
            len(history["transitions"]) != len(history["snapshots"]) - 1):
        return report(["invalid_governance_history"])
    if (not isinstance(anchor, dict) or set(anchor) != {
            "schema", "first_revision", "first_policy_sha256",
            "last_revision", "last_policy_sha256"
    } or anchor.get("schema") != PIN_SCHEMA):
        return report(["invalid_independent_history_pin"])
    if (not isinstance(controller_trust, dict) or set(controller_trust) != {
            "schema", "controllers"
    } or controller_trust.get("schema") != CONTROLLER_TRUST_SCHEMA or
            not isinstance(controller_trust.get("controllers"), dict) or
            not controller_trust["controllers"]):
        return report(["invalid_controller_trust"])
    first, last = anchor["first_revision"], anchor["last_revision"]
    if (type(first) is not int or first < 0 or type(last) is not int or
            last != first + len(history["snapshots"]) - 1 or
            not is_hex(anchor["first_policy_sha256"], 64) or
            not is_hex(anchor["last_policy_sha256"], 64)):
        return report(["invalid_independent_history_pin_fields"])

    controllers = controller_trust["controllers"]
    for key_id, record in controllers.items():
        if (not isinstance(key_id, str) or not key_id or
                not isinstance(record, dict) or set(record) != {"public_key_hex", "status"} or
                not is_hex(record.get("public_key_hex"), 64) or
                record.get("status") not in ("active", "revoked")):
            errors.append("invalid_controller_registry_record")
    if errors:
        return report(errors)

    verified: list[tuple[dict, dict, str]] = []
    for i, snapshot in enumerate(history["snapshots"]):
        if not isinstance(snapshot, dict) or set(snapshot) != {
            "policy", "review", "receipt", "inputs", "reviewer_trust"
        }:
            errors.append(f"invalid_snapshot:{i}")
            continue
        policy = snapshot["policy"]
        if not isinstance(policy, dict) or type(policy.get("revision")) is not int:
            errors.append(f"invalid_snapshot_policy:{i}")
            continue
        if policy["revision"] != first + i:
            errors.append(f"policy_revision_gap:{i}")
        try:
            h = canonical_hash(policy)
            pin = {
                "schema": "palaco.go20-governance-policy-pin.v1",
                "minimum_revision": first + i, "policy_sha256": h,
            }
            validation = assess_governance(
                snapshot["review"], snapshot["receipt"], snapshot["inputs"],
                snapshot["reviewer_trust"], policy, pin)
        except (TypeError, ValueError, KeyError, IndexError, AttributeError,
                OverflowError, RecursionError) as exc:
            errors.append(f"malformed_snapshot:{i}:{type(exc).__name__}")
            continue
        if not validation["governance_valid"]:
            errors.extend(f"snapshot:{i}:{err}" for err in validation["errors"])
        verified.append((policy, snapshot["reviewer_trust"], h))
    if len(verified) != len(history["snapshots"]):
        return report(errors, len(verified))
    if verified[0][2] != anchor["first_policy_sha256"]:
        errors.append("independent_first_policy_mismatch")
    if verified[-1][2] != anchor["last_policy_sha256"]:
        errors.append("independent_last_policy_mismatch")
    rotations = 0
    for i, transition in enumerate(history["transitions"]):
        if not isinstance(transition, dict) or set(transition) != {
            "from_revision", "to_revision", "from_policy_sha256", "to_policy_sha256",
            "changed_roles", "controller_id", "signature_ed25519_hex"
        }:
            errors.append(f"invalid_transition:{i}")
            continue
        old, old_trust, old_hash = verified[i]
        new, new_trust, new_hash = verified[i + 1]
        if (type(transition["from_revision"]) is not int or
                type(transition["to_revision"]) is not int or
                transition["from_revision"] != first + i or
                transition["to_revision"] != first + i + 1 or
                transition["from_policy_sha256"] != old_hash or
                transition["to_policy_sha256"] != new_hash):
            errors.append(f"transition_link_mismatch:{i}")
        declared = transition["changed_roles"]
        if (not isinstance(declared, list) or
                len(declared) > 1 or len(declared) != len(set(map(str, declared))) or
                any(role not in ROLES for role in declared)):
            errors.append(f"invalid_rotation_declaration:{i}")
            continue
        actual = [role for role in ROLES
                  if old["reviewers"][role]["reviewer_id"] != new["reviewers"][role]["reviewer_id"] or
                  old_trust["reviewers"].get(old["reviewers"][role]["reviewer_id"]) !=
                  new_trust["reviewers"].get(new["reviewers"][role]["reviewer_id"])]
        if set(actual) != set(declared):
            errors.append(f"unreported_reviewer_change:{i}")
        if old["prohibited_capabilities"] != new["prohibited_capabilities"]:
            errors.append(f"prohibition_policy_changed:{i}")
        if old["repository"] != new["repository"]:
            errors.append(f"repository_changed:{i}")
        controller = transition["controller_id"]
        record = controllers.get(controller) if isinstance(controller, str) else None
        if (not isinstance(record, dict) or record.get("status") != "active" or
                not is_hex(record.get("public_key_hex"), 64)):
            errors.append(f"untrusted_or_revoked_controller:{i}")
            continue
        # A governance controller cannot also be a policy reviewer in either snapshot.
        reviewer_public_keys = {
            row.get("public_key_hex")
            for trust in (old_trust, new_trust)
            for row in trust["reviewers"].values() if isinstance(row, dict)
        }
        if record["public_key_hex"] in reviewer_public_keys:
            errors.append(f"controller_reviewer_key_overlap:{i}")
        if not is_hex(transition["signature_ed25519_hex"], 128):
            errors.append(f"invalid_transition_signature_encoding:{i}")
            continue
        statement = {
            "schema": TRANSITION_SCHEMA,
            **{key: transition[key] for key in transition if key != "signature_ed25519_hex"},
        }
        issue = verify_signature(record["public_key_hex"],
                                 transition["signature_ed25519_hex"], statement)
        if issue:
            errors.append(f"transition_signature:{i}:{issue}")
        if not issue and set(actual) == set(declared) and len(actual) == 1:
            rotations += 1
    return report(errors, len(verified), rotations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--independent-pin", type=Path, required=True)
    parser.add_argument("--controller-trust", type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        output = verify_history(read(args.history), read(args.independent_pin),
                                read(args.controller_trust))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError) as exc:
        output = report(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if output["history_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
