#!/usr/bin/env python3
"""GO-20 v46: verify chained checkpoint publication receipts, offline only.

Every sequence has a hash-linked checkpoint and at least a pinned quorum of
independently signed delivery receipts. The latest checkpoint must also pass
the complete v45 witnessed checkpoint assessor. No network publication
occurs and signed receipts do not prove remote durable availability.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_transparency_checkpoint_views import assess as assess_v45, CHECKPOINT_SCHEMA

SCHEMA = "palaco.go20-checkpoint-receipt-continuity.v1"
PIN_SCHEMA = "palaco.go20-checkpoint-receipt-continuity-pin.v1"
RECEIPT_SCHEMA = "palaco.go20-checkpoint-delivery-receipt.v1"
ZERO = "0" * 64
MAX_ENTRIES = 6


def verdict(errors, checked=0, receipts=0):
    return {
        "schema": "palaco.go20-checkpoint-receipt-continuity-verdict.v1",
        "publication_evidence_valid": not errors,
        "checkpoints_verified": checked,
        "receipts_verified": receipts,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "checkpoint_published": False,
        "remote_publication_verified": False,
        "fence_performed": False, "failover_authorized": False,
        "promotion_performed": False, "release_authorized": False,
        "merge_authorized": False, "deployment_authorized": False,
        "production_commit_performed": False,
    }


def verify_continuity(evidence, anchor, trust, v45_sources):
    try:
        for item in (evidence, anchor, trust, v45_sources):
            validate_shape(item)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(evidence, dict) or set(evidence) != {"schema", "entries"} or
            evidence.get("schema") != SCHEMA or
            not isinstance(evidence["entries"], list) or
            not 2 <= len(evidence["entries"]) <= MAX_ENTRIES):
        return verdict(["invalid_checkpoint_chain"])
    if (not isinstance(anchor, dict) or set(anchor) != {
            "schema", "first_sequence", "last_sequence", "first_entry_sha256",
            "last_entry_sha256", "trust_sha256", "quorum"
    } or anchor.get("schema") != PIN_SCHEMA or
            type(anchor.get("first_sequence")) is not int or
            anchor["first_sequence"] < 0 or
            type(anchor.get("last_sequence")) is not int or
            anchor["last_sequence"] != anchor["first_sequence"] + len(evidence["entries"]) - 1 or
            type(anchor.get("quorum")) is not int or
            anchor["quorum"] < 2 or
            any(not is_hex(anchor.get(key), 64) for key in (
                "first_entry_sha256", "last_entry_sha256", "trust_sha256"))):
        return verdict(["invalid_independent_continuity_pin"])
    if (not isinstance(trust, dict) or set(trust) != {"schema", "witnesses"} or
            trust.get("schema") != "palaco.go20-transparency-witness-trust.v1" or
            not isinstance(trust.get("witnesses"), dict) or
            not 3 <= len(trust["witnesses"]) <= 7 or
            anchor["quorum"] > len(trust["witnesses"])):
        return verdict(["invalid_receipt_trust"])
    if canonical_hash(trust) != anchor["trust_sha256"]:
        return verdict(["receipt_trust_anchor_mismatch"])
    if (not isinstance(v45_sources, dict) or set(v45_sources) != {
            "left_history", "left_pin", "right_history", "right_pin",
            "revocations", "signed_register", "v44_pin", "views",
            "trust", "independent_pin"
    }):
        return verdict(["invalid_v45_sources"])
    verified = assess_v45(*(v45_sources[k] for k in (
        "left_history", "left_pin", "right_history", "right_pin",
        "revocations", "signed_register", "v44_pin", "views",
        "trust", "independent_pin")))
    if not verified["transparency_evidence_valid"]:
        return verdict(["v45:" + issue for issue in verified["errors"]])
    if canonical_hash(v45_sources["trust"]) != canonical_hash(trust):
        return verdict(["v45_witness_trust_mismatch"])

    errors, counted, receipts = [], 0, 0
    preceding = ZERO
    head_checkpoint = v45_sources["views"]["observations"][0]["checkpoint"]
    for index, entry in enumerate(evidence["entries"]):
        sequence = anchor["first_sequence"] + index
        if (not isinstance(entry, dict) or set(entry) != {
                "sequence", "previous_entry_sha256", "checkpoint", "receipts"
        } or type(entry.get("sequence")) is not int or
                entry["sequence"] != sequence or
                not is_hex(entry.get("previous_entry_sha256"), 64) or
                not isinstance(entry.get("checkpoint"), dict) or
                not isinstance(entry.get("receipts"), list) or
                not 2 <= len(entry["receipts"]) <= 7):
            errors.append(f"invalid_or_missing_checkpoint:{index}")
            continue
        if entry["previous_entry_sha256"] != preceding:
            errors.append(f"checkpoint_chain_link_mismatch:{index}")
        cp = entry["checkpoint"]
        if (set(cp) != {"schema", "repository", "sequence",
                "last_epoch", "history_sha256", "revocations_sha256"} or
                cp.get("schema") != CHECKPOINT_SCHEMA or
                cp.get("repository") != "Maurits-pixe/PALACO" or
                type(cp.get("sequence")) is not int or cp["sequence"] != sequence or
                type(cp.get("last_epoch")) is not int or cp["last_epoch"] < 0 or
                not is_hex(cp.get("history_sha256"), 64) or
                not is_hex(cp.get("revocations_sha256"), 64)):
            errors.append(f"invalid_checkpoint_content:{index}")
            continue
        if index == len(evidence["entries"]) - 1 and cp != head_checkpoint:
            errors.append("final_checkpoint_does_not_match_v45")
        cp_hash = canonical_hash(cp)
        used_ids, used_orgs, used_domains, used_keys = set(), set(), set(), set()
        valid = 0
        for receipt_index, receipt in enumerate(entry["receipts"]):
            if (not isinstance(receipt, dict) or set(receipt) != {
                    "witness_id", "signature_ed25519_hex"
            } or not isinstance(receipt.get("witness_id"), str) or
                    receipt["witness_id"] in used_ids or
                    receipt["witness_id"] not in trust["witnesses"]):
                errors.append(f"duplicate_or_unknown_receipt:{index}:{receipt_index}")
                continue
            wid = receipt["witness_id"]
            used_ids.add(wid)
            witness = trust["witnesses"][wid]
            if (not isinstance(witness, dict) or set(witness) != {
                    "public_key_hex", "organization_id", "domain_id", "status"
            } or not is_hex(witness.get("public_key_hex"), 64) or
                    witness.get("status") != "active" or
                    not isinstance(witness.get("organization_id"), str) or
                    not witness["organization_id"] or
                    not isinstance(witness.get("domain_id"), str) or
                    not witness["domain_id"]):
                errors.append(f"invalid_receipt_signer:{index}:{wid}")
                continue
            org, domain, key = witness["organization_id"], witness["domain_id"], witness["public_key_hex"]
            if org in used_orgs or domain in used_domains or key in used_keys:
                errors.append(f"receipt_custody_overlap:{index}:{wid}")
                continue
            used_orgs.add(org)
            used_domains.add(domain)
            used_keys.add(key)
            statement = {
                "schema": RECEIPT_SCHEMA,
                "repository": "Maurits-pixe/PALACO",
                "sequence": sequence,
                "checkpoint_sha256": cp_hash,
                "previous_entry_sha256": entry["previous_entry_sha256"],
                "trust_sha256": canonical_hash(trust),
                "witness_id": wid,
                "decision": "HOLD", "authorization": "DENY",
            }
            signature = receipt["signature_ed25519_hex"]
            if (not is_hex(signature, 128) or
                    verify_signature(key, signature, statement) is not None):
                errors.append(f"invalid_receipt_signature:{index}:{wid}")
                continue
            valid += 1
        if valid < anchor["quorum"]:
            errors.append(f"missing_publication_receipts:{index}")
        else:
            counted += 1
        receipts += valid
        preceding = canonical_hash(entry)
        if index == 0 and preceding != anchor["first_entry_sha256"]:
            errors.append("first_checkpoint_anchor_mismatch")
    if preceding != anchor["last_entry_sha256"]:
        errors.append("last_checkpoint_anchor_mismatch")
    return verdict(errors, counted, receipts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("chain", "independent-pin", "trust", "v45-evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        output = verify_continuity(read(args.chain), read(args.independent_pin),
                                   read(args.trust), read(args.v45_evidence))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        output = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if output["publication_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
