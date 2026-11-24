#!/usr/bin/env python3
"""GO-20 v42: offline Ed25519 fencing quorum verification (never promotion).

Trust registry and monotonic epoch pin must be provisioned independently.
A signed claim is evidence only: it cannot prove that a physical fence
occurred, nor may it authorize a leader, deployment or production write.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from pr_attestation_chain import verify_signature
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_recovery_fencing import check as check_fencing

SCHEMA = "palaco.go20-signed-fencing-quorum.v1"
TRUST_SCHEMA = "palaco.go20-fencing-quorum-trust.v1"
PIN_SCHEMA = "palaco.go20-fencing-quorum-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-fencing-quorum-statement.v1"


def verdict(errors, votes=0):
    return {
        "schema": "palaco.go20-signed-fencing-quorum-verdict.v1",
        "quorum_evidence_valid": not errors,
        "signatures_verified": votes,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "fence_performed": False, "promotion_performed": False,
        "failover_authorized": False, "release_authorized": False,
        "merge_authorized": False, "deployment_authorized": False,
        "production_commit_performed": False,
    }


def verify_quorum(primary, candidate, handoff_pin, transition, transition_pin,
                  signed_votes, trust, independent_pin):
    try:
        for value in (primary, candidate, handoff_pin, transition,
                      transition_pin, signed_votes, trust, independent_pin):
            validate_shape(value)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(trust, dict) or set(trust) != {"schema", "members"} or
            trust.get("schema") != TRUST_SCHEMA or
            not isinstance(trust.get("members"), dict) or
            not 3 <= len(trust["members"]) <= 7):
        return verdict(["invalid_quorum_trust"])
    if (not isinstance(signed_votes, dict) or
            set(signed_votes) != {"schema", "votes"} or
            signed_votes.get("schema") != SCHEMA or
            not isinstance(signed_votes.get("votes"), list) or
            not 2 <= len(signed_votes["votes"]) <= 7):
        return verdict(["invalid_signed_votes"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "trust_sha256", "transition_sha256", "minimum_epoch",
            "minimum_signatures", "required_fence_controller"
        } or independent_pin.get("schema") != PIN_SCHEMA or
            type(independent_pin.get("minimum_epoch")) is not int or
            independent_pin["minimum_epoch"] < 0 or
            type(independent_pin.get("minimum_signatures")) is not int or
            independent_pin["minimum_signatures"] < 2 or
            independent_pin["minimum_signatures"] > len(trust["members"]) or
            not isinstance(independent_pin.get("required_fence_controller"), str) or
            not independent_pin["required_fence_controller"]):
        return verdict(["invalid_quorum_pin"])
    if (canonical_hash(trust) != independent_pin["trust_sha256"] or
            canonical_hash(transition) != independent_pin["transition_sha256"]):
        return verdict(["independent_quorum_anchor_mismatch"])
    if (not isinstance(transition, dict) or
            type(transition.get("candidate_epoch")) is not int or
            transition["candidate_epoch"] < independent_pin["minimum_epoch"]):
        return verdict(["quorum_epoch_rollback"])
    base = check_fencing(primary, candidate, handoff_pin, transition, transition_pin)
    if not base["fencing_evidence_valid"]:
        return verdict(["fencing:" + e for e in base["errors"]])
    seen_ids, orgs, domains, keys = set(), set(), set(), set()
    errors = []
    signed_count = 0
    controller_verified = False
    for index, vote in enumerate(signed_votes["votes"]):
        if (not isinstance(vote, dict) or set(vote) != {
                "member_id", "signature_ed25519_hex"
        } or not isinstance(vote.get("member_id"), str) or
                vote["member_id"] not in trust["members"] or
                vote["member_id"] in seen_ids):
            errors.append(f"unknown_or_duplicate_voter:{index}")
            continue
        member_id = vote["member_id"]
        seen_ids.add(member_id)
        record = trust["members"][member_id]
        if (not isinstance(record, dict) or set(record) != {
                "public_key_hex", "organization_id", "control_domain_id",
                "role", "status"
        } or not is_hex(record.get("public_key_hex"), 64) or
                not isinstance(record.get("organization_id"), str) or
                not record["organization_id"] or
                not isinstance(record.get("control_domain_id"), str) or
                not record["control_domain_id"] or
                record["role"] not in ("fence_controller", "observer") or
                record["status"] != "active"):
            errors.append(f"revoked_or_invalid_voter:{member_id}")
            continue
        org = record["organization_id"]
        domain = record["control_domain_id"]
        key = record["public_key_hex"]
        if org in orgs or domain in domains or key in keys:
            errors.append(f"voter_custody_overlap:{member_id}")
            continue
        orgs.add(org)
        domains.add(domain)
        keys.add(key)
        statement = {
            "schema": STATEMENT_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "candidate_epoch": transition["candidate_epoch"],
            "transition_sha256": canonical_hash(transition),
            "trust_sha256": canonical_hash(trust),
            "member_id": member_id,
            "decision": "HOLD",
            "authorization": "DENY",
        }
        signature = vote["signature_ed25519_hex"]
        if not is_hex(signature, 128):
            errors.append(f"invalid_signature_encoding:{member_id}")
            continue
        issue = verify_signature(key, signature, statement)
        if issue:
            errors.append(f"invalid_voter_signature:{member_id}:{issue}")
            continue
        signed_count += 1
        if member_id == independent_pin["required_fence_controller"] and record["role"] == "fence_controller":
            controller_verified = True
    if len(seen_ids) < independent_pin["minimum_signatures"] or signed_count < independent_pin["minimum_signatures"]:
        errors.append("quorum_not_met")
    if not controller_verified:
        errors.append("required_fence_controller_missing")
    return verdict(errors, signed_count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("primary", "candidate", "handoff-pin", "transition",
                 "transition-pin", "signed-votes", "trust", "independent-pin"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        def load(path):
            if not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError("missing_or_oversize_file")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        out = verify_quorum(*(load(getattr(args, name.replace("-", "_"))) for name in (
            "primary", "candidate", "handoff-pin", "transition", "transition-pin",
            "signed-votes", "trust", "independent-pin")))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out["quorum_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
