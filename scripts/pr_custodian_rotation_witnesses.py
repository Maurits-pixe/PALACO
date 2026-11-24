#!/usr/bin/env python3
"""GO-20 v54: independently witnessed custodian-key succession and revocation.

Reverify both full v53 views. Each transition is signed by an independent
Ed25519 witness quorum, bound to both registry hashes, the rotation record
set, the immutable historical view and an externally pinned revocation list.
Revocations are effective at a specified round and cannot be silently
forgotten. Evidence-only, with no production authorization or key operations.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_attestation_chain import verify_signature
from pr_ledger_receipt_succession import assess as assess_v53

SCHEMA = "palaco.go20-custodian-rotation-witnesses.v1"
TRUST_SCHEMA = "palaco.go20-rotation-independent-witness-trust.v1"
REVOKE_SCHEMA = "palaco.go20-custodian-key-revocations.v1"
PIN_SCHEMA = "palaco.go20-rotation-witness-independent-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-custodian-rotation-witness-statement.v1"


def verdict(errors, transitions=0, signatures=0):
    return {
        "schema": "palaco.go20-custodian-rotation-witness-verdict.v1",
        "rotation_evidence_valid": not errors,
        "transitions_verified": transitions,
        "witness_signatures_verified": signatures,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "trust_registry_promoted": False, "revocation_enforced_in_production": False,
        "history_restored": False, "archive_published": False,
        "failover_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def assess(left, left_pin, right, right_pin, head, testimony, witness_trust,
           revocations, independent_pin):
    try:
        for x in (left, left_pin, right, right_pin, head, testimony,
                  witness_trust, revocations, independent_pin):
            validate_shape(x)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])

    if (not isinstance(testimony, dict) or set(testimony) != {"schema", "transitions"} or
            testimony.get("schema") != SCHEMA or
            not isinstance(testimony.get("transitions"), list) or
            not 1 <= len(testimony["transitions"]) <= 3):
        return verdict(["invalid_witness_transitions"])
    if (not isinstance(witness_trust, dict) or set(witness_trust) != {"schema", "witnesses"} or
            witness_trust.get("schema") != TRUST_SCHEMA or
            not isinstance(witness_trust.get("witnesses"), dict) or
            not 3 <= len(witness_trust["witnesses"]) <= 7):
        return verdict(["invalid_witness_trust"])
    if (not isinstance(revocations, dict) or set(revocations) != {"schema", "entries"} or
            revocations.get("schema") != REVOKE_SCHEMA or
            not isinstance(revocations.get("entries"), list) or
            len(revocations["entries"]) > 30):
        return verdict(["invalid_revocations"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "view_sha256", "witness_trust_sha256", "revocations_sha256",
            "minimum_round", "quorum"
    } or independent_pin.get("schema") != PIN_SCHEMA or
            any(not is_hex(independent_pin.get(k), 64) for k in (
                "view_sha256", "witness_trust_sha256", "revocations_sha256")) or
            type(independent_pin.get("minimum_round")) is not int or
            independent_pin["minimum_round"] < 2 or
            type(independent_pin.get("quorum")) is not int or
            not 2 <= independent_pin["quorum"] <= len(witness_trust["witnesses"])):
        return verdict(["invalid_independent_witness_pin"])
    if (canonical_hash(left) != independent_pin["view_sha256"] or
            canonical_hash(witness_trust) != independent_pin["witness_trust_sha256"] or
            canonical_hash(revocations) != independent_pin["revocations_sha256"]):
        return verdict(["independent_anchor_mismatch"])
    try:
        existing = assess_v53(left, left_pin, right, right_pin, head)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            RecursionError, OverflowError, MemoryError) as exc:
        return verdict(["malformed_v53:" + type(exc).__name__])
    if not existing["succession_evidence_valid"]:
        return verdict(["v53:" + x for x in existing["errors"]])
    if left_pin["last_round"] < independent_pin["minimum_round"]:
        return verdict(["round_rollback"])
    if len(testimony["transitions"]) != len(left["rounds"]) - 1:
        return verdict(["missing_witness_transition"])

    errors = []
    revoked = set()
    for i, item in enumerate(revocations["entries"]):
        if (not isinstance(item, dict) or set(item) != {
                "custodian_id", "public_key_hex", "effective_round"
        } or not isinstance(item.get("custodian_id"), str) or
                not item["custodian_id"] or
                not is_hex(item.get("public_key_hex"), 64) or
                type(item.get("effective_round")) is not int or
                not 1 <= item["effective_round"] <= left_pin["last_round"]):
            errors.append(f"invalid_revocation:{i}")
            continue
        key = (item["custodian_id"], item["public_key_hex"])
        if key in revoked:
            errors.append(f"duplicate_revocation:{i}")
        revoked.add(key)

    checked, signed = 0, 0
    # Revocation is effective at its declared round; also examine the first
    # retained snapshot so an already-revoked genesis key cannot slip through.
    for index, round_item in enumerate(left["rounds"]):
        members = round_item["sources"]["trust"]["custodians"]
        for custodian_id, record in members.items():
            if any(isinstance(item, dict) and
                   item.get("custodian_id") == custodian_id and
                   item.get("public_key_hex") == record["public_key_hex"] and
                   type(item.get("effective_round")) is int and
                   item["effective_round"] <= round_item["round"]
                   for item in revocations["entries"]):
                errors.append(f"revoked_key_present_in_history:{index}:{custodian_id}")
    for i, pair in enumerate(zip(left["rounds"][:-1], left["rounds"][1:])):
        previous, current = pair
        old_trust = previous["sources"]["trust"]["custodians"]
        new_trust = current["sources"]["trust"]["custodians"]
        for custodian_id, record in new_trust.items():
            if any(item.get("custodian_id") == custodian_id and
                   item.get("public_key_hex") == record["public_key_hex"] and
                   item.get("effective_round", 1 << 30) <= current["round"]
                   for item in revocations["entries"] if isinstance(item, dict)):
                errors.append(f"revoked_key_reactivated:{i}:{custodian_id}")
        witness_record = testimony["transitions"][i]
        if (not isinstance(witness_record, dict) or set(witness_record) != {
                "round", "old_trust_sha256", "new_trust_sha256",
                "rotations_sha256", "signatures"
        } or type(witness_record.get("round")) is not int or
                witness_record["round"] != current["round"] or
                not isinstance(witness_record.get("signatures"), list) or
                not 2 <= len(witness_record["signatures"]) <= 7):
            errors.append(f"invalid_transition:{i}")
            continue
        rotated = [r for r in left["rotations"] if r["round"] == current["round"]]
        expected = {
            "round": current["round"],
            "old_trust_sha256": canonical_hash(previous["sources"]["trust"]),
            "new_trust_sha256": canonical_hash(current["sources"]["trust"]),
            "rotations_sha256": canonical_hash(rotated),
        }
        if any(witness_record.get(k) != v for k, v in expected.items()):
            errors.append(f"transition_binding_mismatch:{i}")
            continue
        used_ids, orgs, domains, keys = set(), set(), set(), set()
        valid = 0
        for j, vote in enumerate(witness_record["signatures"]):
            if (not isinstance(vote, dict) or set(vote) != {
                    "witness_id", "signature_ed25519_hex"
            } or not isinstance(vote.get("witness_id"), str) or
                    vote["witness_id"] not in witness_trust["witnesses"] or
                    vote["witness_id"] in used_ids):
                errors.append(f"duplicate_or_unknown_witness:{i}:{j}")
                continue
            wid = vote["witness_id"]
            used_ids.add(wid)
            witness = witness_trust["witnesses"][wid]
            if (not isinstance(witness, dict) or set(witness) != {
                    "public_key_hex", "organization_id", "domain_id", "status"
            } or not is_hex(witness.get("public_key_hex"), 64) or
                    witness.get("status") != "active" or
                    not isinstance(witness.get("organization_id"), str) or
                    not witness["organization_id"] or
                    not isinstance(witness.get("domain_id"), str) or
                    not witness["domain_id"]):
                errors.append(f"invalid_witness:{i}:{wid}")
                continue
            org, domain, key = (witness["organization_id"],
                                witness["domain_id"], witness["public_key_hex"])
            if org in orgs or domain in domains or key in keys:
                errors.append(f"witness_custody_overlap:{i}:{wid}")
                continue
            orgs.add(org)
            domains.add(domain)
            keys.add(key)
            statement = {
                "schema": STATEMENT_SCHEMA, **expected,
                "view_sha256": independent_pin["view_sha256"],
                "revocations_sha256": independent_pin["revocations_sha256"],
                "witness_trust_sha256": independent_pin["witness_trust_sha256"],
                "witness_id": wid,
                "decision": "HOLD", "authorization": "DENY",
            }
            if (not is_hex(vote.get("signature_ed25519_hex"), 128) or
                    verify_signature(key, vote["signature_ed25519_hex"],
                                     statement) is not None):
                errors.append(f"invalid_witness_signature:{i}:{wid}")
                continue
            valid += 1
        signed += valid
        if valid < independent_pin["quorum"]:
            errors.append(f"insufficient_rotation_witness_quorum:{i}")
        else:
            checked += 1
    return verdict(errors, checked, signed)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    names = ("left", "left-pin", "right", "right-pin", "head",
             "testimony", "witness-trust", "revocations", "independent-pin")
    for n in names:
        p.add_argument("--" + n, required=True, type=Path)
    args = p.parse_args()
    try:
        def load(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_input")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = assess(*(load(getattr(args, n.replace("-", "_"))) for n in names))
    except (OSError, TypeError, ValueError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["rotation_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
