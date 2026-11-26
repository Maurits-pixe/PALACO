#!/usr/bin/env python3
"""GO-20 v62: independently pinned, signed custody of each v61 succession round.

Every v61 round must have exact archived copies and two independent Ed25519
custody acknowledgements. A fully reverified v61 history and externally
pinned custody register are mandatory. This is offline supplied evidence:
it cannot prove remote publication, network availability, or actual custody.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_reconstruction_head_succession import assess as assess_v61

SCHEMA = "palaco.go20-head-succession-custody.v1"
PIN_SCHEMA = "palaco.go20-head-succession-custody-pin.v1"
TRUST_SCHEMA = "palaco.go20-head-succession-custodians.v1"
STATEMENT_SCHEMA = "palaco.go20-head-succession-custody-statement.v1"


def verdict(errors, rounds=0, signatures=0):
    return {
        "schema": "palaco.go20-head-succession-custody-verdict.v1",
        "custody_evidence_valid": not errors,
        "rounds_verified": rounds,
        "custodian_signatures_verified": signatures,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "remote_publication_verified": False,
        "remote_storage_reachable": False,
        "independent_custody_established": False,
        "history_restored": False,
        "recovery_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess(v61_sources, copies, trust, independent_pin):
    try:
        for value in (v61_sources, copies, trust, independent_pin):
            validate_shape(value)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(v61_sources, dict) or set(v61_sources) != {
            "left", "left_pin", "right", "right_pin", "independent_head"
    } or not isinstance(copies, dict) or
            set(copies) != {"schema", "rounds"} or
            copies.get("schema") != SCHEMA or
            not isinstance(copies.get("rounds"), list) or
            not 2 <= len(copies["rounds"]) <= 4):
        return verdict(["invalid_custody_bundle"])
    if (not isinstance(trust, dict) or set(trust) != {"schema", "members"} or
            trust.get("schema") != TRUST_SCHEMA or
            not isinstance(trust.get("members"), dict) or
            not 2 <= len(trust["members"]) <= 5):
        return verdict(["invalid_custodian_register"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "v61_sources_sha256", "history_sha256",
            "copies_sha256", "custodian_trust_sha256", "minimum_round",
            "minimum_receipts"
    } or independent_pin.get("schema") != PIN_SCHEMA or
            any(not is_hex(independent_pin.get(k), 64) for k in (
                "v61_sources_sha256", "history_sha256",
                "copies_sha256", "custodian_trust_sha256")) or
            type(independent_pin.get("minimum_round")) is not int or
            independent_pin["minimum_round"] < 2 or
            type(independent_pin.get("minimum_receipts")) is not int or
            not 2 <= independent_pin["minimum_receipts"] <= len(trust["members"])):
        return verdict(["invalid_external_custody_pin"])
    if (canonical_hash(v61_sources) != independent_pin["v61_sources_sha256"] or
            canonical_hash(v61_sources["left"]) != independent_pin["history_sha256"] or
            canonical_hash(copies) != independent_pin["copies_sha256"] or
            canonical_hash(trust) != independent_pin["custodian_trust_sha256"]):
        return verdict(["independent_custody_anchor_mismatch"])
    try:
        previous = assess_v61(*(v61_sources[k] for k in (
            "left", "left_pin", "right", "right_pin", "independent_head")))
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["malformed_v61:" + type(exc).__name__])
    if not previous["succession_evidence_valid"]:
        return verdict(["v61:" + err for err in previous["errors"]])
    original = v61_sources["left"]["rounds"]
    if (len(original) != len(copies["rounds"]) or
            original[-1]["round"] < independent_pin["minimum_round"]):
        return verdict(["missing_or_rollback_historical_publication"])
    errors, counted, signed = [], 0, 0
    for i, record in enumerate(copies["rounds"]):
        expected = original[i]
        if (not isinstance(record, dict) or set(record) != {
                "round", "full_round_copy", "receipts"
            } or type(record.get("round")) is not int or
                record["round"] != expected["round"] or
                not isinstance(record.get("full_round_copy"), dict) or
                not isinstance(record.get("receipts"), list) or
                not independent_pin["minimum_receipts"] <= len(record["receipts"]) <= 5):
            errors.append(f"missing_round_or_receipts:{i}")
            continue
        if (record["full_round_copy"] != expected or
                canonical_hash(record["full_round_copy"]) != canonical_hash(expected)):
            errors.append(f"mismatched_historical_round_copy:{i}")
            continue
        used, orgs, domains, keys = set(), set(), set(), set()
        count = 0
        for j, receipt in enumerate(record["receipts"]):
            if (not isinstance(receipt, dict) or set(receipt) != {
                    "custodian_id", "signature_ed25519_hex"
            } or not isinstance(receipt.get("custodian_id"), str) or
                    receipt["custodian_id"] not in trust["members"] or
                    receipt["custodian_id"] in used):
                errors.append(f"unknown_or_duplicate_custodian:{i}:{j}")
                continue
            mid = receipt["custodian_id"]
            used.add(mid)
            member = trust["members"][mid]
            if (not isinstance(member, dict) or set(member) != {
                    "public_key_hex", "organization_id", "domain_id", "status"
            } or not is_hex(member.get("public_key_hex"), 64) or
                    member.get("status") != "active" or
                    not isinstance(member.get("organization_id"), str) or
                    not member["organization_id"] or
                    not isinstance(member.get("domain_id"), str) or
                    not member["domain_id"]):
                errors.append(f"invalid_custodian:{i}:{mid}")
                continue
            org, domain, key = (member["organization_id"], member["domain_id"],
                                member["public_key_hex"])
            if org in orgs or domain in domains or key in keys:
                errors.append(f"overlapping_custodian_domains:{i}:{mid}")
                continue
            orgs.add(org)
            domains.add(domain)
            keys.add(key)
            statement = {
                "schema": STATEMENT_SCHEMA,
                "repository": "Maurits-pixe/PALACO",
                "round": record["round"],
                "round_sha256": canonical_hash(expected),
                "previous_sha256": expected["previous_sha256"],
                "history_sha256": independent_pin["history_sha256"],
                "v61_sources_sha256": independent_pin["v61_sources_sha256"],
                "custodian_trust_sha256": independent_pin["custodian_trust_sha256"],
                "custodian_id": mid,
                "decision": "HOLD", "authorization": "DENY",
            }
            if (not is_hex(receipt.get("signature_ed25519_hex"), 128) or
                    verify_signature(key, receipt["signature_ed25519_hex"],
                                     statement) is not None):
                errors.append(f"invalid_custody_signature:{i}:{mid}")
                continue
            count += 1
        signed += count
        if count < independent_pin["minimum_receipts"]:
            errors.append(f"insufficient_archived_receipts:{i}")
        else:
            counted += 1
    return verdict(errors, counted, signed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("v61-evidence", "copies", "custodian-trust", "independent-pin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_evidence_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = assess(*(read(getattr(args, name.replace("-", "_"))) for name in (
            "v61-evidence", "copies", "custodian-trust", "independent-pin")))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["custody_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
