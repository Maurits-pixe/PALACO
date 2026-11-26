#!/usr/bin/env python3
"""GO-20 v60: signed external reconstruction-history anchors and reviewer revocation.

Offline-only verification of v59, independent Ed25519 head witnesses,
historical reviewer-key revocations and two observer recovery decisions.
No real-world signer independence, storage availability, or production
authorization is established. A positive proof always retains HOLD/DENY.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_reconstruction_review_history import assess as assess_v59

SCHEMA = "palaco.go20-reconstruction-head-witnesses.v1"
TRUST_SCHEMA = "palaco.go20-reconstruction-head-witness-trust.v1"
REVOKE_SCHEMA = "palaco.go20-historical-reviewer-revocations.v1"
PIN_SCHEMA = "palaco.go20-reconstruction-head-independent-pin.v1"
HEAD_STATEMENT = "palaco.go20-reconstruction-head-witness-statement.v1"
DECISION_STATEMENT = "palaco.go20-reconstruction-recovery-decision.v1"


def verdict(errors, witnesses=0, decisions=0):
    return {
        "schema": "palaco.go20-reconstruction-head-witness-verdict.v1",
        "head_evidence_valid": not errors,
        "head_witnesses_verified": witnesses,
        "decisions_verified": decisions,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "reviewer_revocations_enforced_in_production": False,
        "restoration_performed": False,
        "recovery_authorized": False,
        "trust_registry_promoted": False,
        "failover_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess(sources, evidence, witness_trust, revocations, pin):
    try:
        for item in (sources, evidence, witness_trust, revocations, pin):
            validate_shape(item)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(sources, dict) or set(sources) != {
                "left", "left_pin", "right", "right_pin", "head"
            } or not isinstance(evidence, dict) or
            set(evidence) != {"schema", "witnesses", "decisions"} or
            evidence.get("schema") != SCHEMA or
            not isinstance(evidence.get("witnesses"), list) or
            not 2 <= len(evidence["witnesses"]) <= 5 or
            not isinstance(evidence.get("decisions"), list) or
            len(evidence["decisions"]) != 2):
        return verdict(["invalid_head_evidence"])
    if (not isinstance(witness_trust, dict) or
            set(witness_trust) != {"schema", "members"} or
            witness_trust.get("schema") != TRUST_SCHEMA or
            not isinstance(witness_trust.get("members"), dict) or
            not 2 <= len(witness_trust["members"]) <= 5):
        return verdict(["invalid_witness_trust"])
    if (not isinstance(revocations, dict) or
            set(revocations) != {"schema", "entries"} or
            revocations.get("schema") != REVOKE_SCHEMA or
            not isinstance(revocations.get("entries"), list) or
            len(revocations["entries"]) > 20):
        return verdict(["invalid_reviewer_revocations"])
    if (not isinstance(pin, dict) or set(pin) != {
                "schema", "v59_sources_sha256", "head_sha256",
                "witness_trust_sha256", "revocations_sha256",
                "minimum_last_round", "minimum_witnesses"
            } or pin.get("schema") != PIN_SCHEMA or
            any(not is_hex(pin.get(k), 64) for k in (
                "v59_sources_sha256", "head_sha256",
                "witness_trust_sha256", "revocations_sha256")) or
            type(pin.get("minimum_last_round")) is not int or
            pin["minimum_last_round"] < 2 or
            type(pin.get("minimum_witnesses")) is not int or
            not 2 <= pin["minimum_witnesses"] <= len(witness_trust["members"])):
        return verdict(["invalid_independent_head_pin"])
    if (canonical_hash(sources) != pin["v59_sources_sha256"] or
            canonical_hash(sources["head"]) != pin["head_sha256"] or
            canonical_hash(witness_trust) != pin["witness_trust_sha256"] or
            canonical_hash(revocations) != pin["revocations_sha256"]):
        return verdict(["external_anchor_mismatch"])
    try:
        prior = assess_v59(*(sources[k] for k in (
            "left", "left_pin", "right", "right_pin", "head")))
    except (ValueError, TypeError, KeyError, AttributeError, IndexError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["malformed_v59:" + type(exc).__name__])
    if not prior["review_history_valid"]:
        return verdict(["v59:" + err for err in prior["errors"]])
    if sources["left_pin"]["last_round"] < pin["minimum_last_round"]:
        return verdict(["history_head_rollback"])

    errors, revoked = [], set()
    for i, item in enumerate(revocations["entries"]):
        if (not isinstance(item, dict) or set(item) != {
                "reviewer_id", "public_key_hex", "effective_round"
            } or not isinstance(item.get("reviewer_id"), str) or
                not item["reviewer_id"] or
                not is_hex(item.get("public_key_hex"), 64) or
                type(item.get("effective_round")) is not int or
                not 1 <= item["effective_round"] <= sources["left_pin"]["last_round"]):
            errors.append(f"invalid_revocation:{i}")
            continue
        identity = (item["reviewer_id"], item["public_key_hex"])
        if identity in revoked:
            errors.append(f"duplicate_revocation:{i}")
        revoked.add(identity)
    # Every retained historical review round is checked against the externally
    # pinned effective revocation date, including the earliest retained round.
    for round_item in sources["left"]["rounds"]:
        members = round_item["sources"]["reviewers"]["members"]
        for rid, member in members.items():
            if any(isinstance(entry, dict) and
                   entry.get("reviewer_id") == rid and
                   entry.get("public_key_hex") == member["public_key_hex"] and
                   type(entry.get("effective_round")) is int and
                   entry["effective_round"] <= round_item["round"]
                   for entry in revocations["entries"]):
                errors.append(f"revoked_reviewer_still_trusted:{round_item['round']}:{rid}")
    witness_ids, organizations, domains, keys = set(), set(), set(), set()
    signed = 0
    for i, item in enumerate(evidence["witnesses"]):
        if (not isinstance(item, dict) or set(item) != {
                "witness_id", "signature_ed25519_hex"
            } or not isinstance(item.get("witness_id"), str) or
                item["witness_id"] not in witness_trust["members"] or
                item["witness_id"] in witness_ids):
            errors.append(f"duplicate_or_unknown_head_witness:{i}")
            continue
        mid = item["witness_id"]
        witness_ids.add(mid)
        member = witness_trust["members"][mid]
        if (not isinstance(member, dict) or set(member) != {
                "public_key_hex", "organization_id", "domain_id", "status"
            } or not is_hex(member.get("public_key_hex"), 64) or
                member.get("status") != "active" or
                not isinstance(member.get("organization_id"), str) or
                not member["organization_id"] or
                not isinstance(member.get("domain_id"), str) or
                not member["domain_id"]):
            errors.append(f"invalid_head_witness:{i}")
            continue
        org, domain, key = (member["organization_id"], member["domain_id"],
                            member["public_key_hex"])
        if org in organizations or domain in domains or key in keys:
            errors.append(f"overlapping_head_witness_custody:{i}")
            continue
        organizations.add(org)
        domains.add(domain)
        keys.add(key)
        statement = {
            "schema": HEAD_STATEMENT,
            "repository": "Maurits-pixe/PALACO",
            "witness_id": mid,
            "v59_sources_sha256": pin["v59_sources_sha256"],
            "head_sha256": pin["head_sha256"],
            "revocations_sha256": pin["revocations_sha256"],
            "witness_trust_sha256": pin["witness_trust_sha256"],
            "minimum_last_round": pin["minimum_last_round"],
            "decision": "HOLD", "authorization": "DENY",
        }
        if (not is_hex(item.get("signature_ed25519_hex"), 128) or
                verify_signature(key, item["signature_ed25519_hex"], statement) is not None):
            errors.append(f"invalid_head_witness_signature:{i}")
            continue
        signed += 1
    if signed < pin["minimum_witnesses"]:
        errors.append("insufficient_independent_head_witnesses")

    decisions, seen = 0, set()
    expected_head = sources["head"]["expected_view_sha256"]
    for i, item in enumerate(evidence["decisions"]):
        if (not isinstance(item, dict) or set(item) != {
                "observer", "view_sha256", "decision", "authorization"
            } or item.get("observer") not in ("left", "right") or
                item["observer"] in seen):
            errors.append(f"missing_or_duplicate_decision:{i}")
            continue
        seen.add(item["observer"])
        view_hash = canonical_hash(sources[item["observer"]])
        if (item.get("view_sha256") != view_hash or
                item["view_sha256"] != expected_head):
            errors.append(f"conflicting_recovery_decision_view:{i}")
            continue
        if item.get("decision") != "HOLD" or item.get("authorization") != "DENY":
            errors.append(f"unauthorized_recovery_decision:{i}")
            continue
        decisions += 1
    if seen != {"left", "right"}:
        errors.append("incomplete_observer_decisions")
    return verdict(errors, signed, decisions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("v59-sources", "head-witnesses", "witness-trust",
                 "reviewer-revocations", "independent-pin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_input")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = assess(*(read(getattr(args, n.replace("-", "_"))) for n in (
            "v59-sources", "head-witnesses", "witness-trust",
            "reviewer-revocations", "independent-pin")))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["head_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
