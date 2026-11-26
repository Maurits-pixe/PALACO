#!/usr/bin/env python3
"""GO-20 v47: verify offline checkpoint-retention custody receipts.

Two independent custodians must attest an identical bounded checkpoint chain.
The full v46 continuity verifier remains a mandatory gate: copied receipts
cannot supply absent original witness quorum or fabricate publication.
No network health probe, physical availability or recovery action is performed.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_checkpoint_receipt_continuity import verify_continuity

SCHEMA = "palaco.go20-checkpoint-retention-custody.v1"
PIN_SCHEMA = "palaco.go20-checkpoint-retention-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-checkpoint-retention-receipt.v1"


def verdict(errors, archived=0, custodians=0):
    return {
        "schema": "palaco.go20-checkpoint-retention-verdict.v1",
        "custody_evidence_valid": not errors,
        "checkpoints_archived": archived,
        "custodians_verified": custodians,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "physical_availability_verified": False,
        "restoration_performed": False,
        "missing_witness_quorum_overridden": False,
        "checkpoint_published": False,
        "fence_performed": False,
        "failover_authorized": False,
        "promotion_performed": False,
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess(chain, chain_pin, witness_trust, v45_evidence,
           archive, custodians, independent_pin):
    try:
        for value in (chain, chain_pin, witness_trust, v45_evidence,
                      archive, custodians, independent_pin):
            validate_shape(value)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(archive, dict) or set(archive) != {"schema", "copies"} or
            archive.get("schema") != SCHEMA or
            not isinstance(archive["copies"], list) or
            not 2 <= len(archive["copies"]) <= 5):
        return verdict(["invalid_archived_copies"])
    if (not isinstance(custodians, dict) or set(custodians) != {"schema", "members"} or
            custodians.get("schema") != "palaco.go20-checkpoint-custodian-trust.v1" or
            not isinstance(custodians["members"], dict) or
            not 2 <= len(custodians["members"]) <= 5):
        return verdict(["invalid_custodian_trust"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "chain_sha256", "trust_sha256", "minimum_custodians",
            "minimum_sequence", "minimum_retained_checkpoints"
    } or independent_pin.get("schema") != PIN_SCHEMA or
            not is_hex(independent_pin.get("chain_sha256"), 64) or
            not is_hex(independent_pin.get("trust_sha256"), 64) or
            type(independent_pin.get("minimum_custodians")) is not int or
            not 2 <= independent_pin["minimum_custodians"] <= len(custodians["members"]) or
            type(independent_pin.get("minimum_sequence")) is not int or
            independent_pin["minimum_sequence"] < 0 or
            type(independent_pin.get("minimum_retained_checkpoints")) is not int or
            independent_pin["minimum_retained_checkpoints"] < 2):
        return verdict(["invalid_retention_pin"])
    if canonical_hash(custodians) != independent_pin["trust_sha256"]:
        return verdict(["custodian_trust_anchor_mismatch"])
    if not isinstance(chain, dict) or not isinstance(chain.get("entries"), list):
        return verdict(["missing_chain"])
    if canonical_hash(chain) != independent_pin["chain_sha256"]:
        return verdict(["archive_chain_anchor_mismatch"])
    if (len(chain["entries"]) < independent_pin["minimum_retained_checkpoints"] or
            not isinstance(chain_pin, dict) or
            type(chain_pin.get("last_sequence")) is not int or
            chain_pin["last_sequence"] < independent_pin["minimum_sequence"]):
        return verdict(["retention_floor_or_sequence_rollback"])
    original = verify_continuity(chain, chain_pin, witness_trust, v45_evidence)
    if not original["publication_evidence_valid"]:
        return verdict(["v46:" + error for error in original["errors"]])

    errors = []
    used_ids, orgs, domains, keys = set(), set(), set(), set()
    valid = 0
    head = canonical_hash(chain)
    for index, copy in enumerate(archive["copies"]):
        if (not isinstance(copy, dict) or set(copy) != {
                "custodian_id", "chain", "signature_ed25519_hex"
        } or not isinstance(copy.get("custodian_id"), str) or
                copy["custodian_id"] not in custodians["members"] or
                copy["custodian_id"] in used_ids or
                not isinstance(copy.get("chain"), dict)):
            errors.append(f"missing_or_duplicate_custodian:{index}")
            continue
        mid = copy["custodian_id"]
        used_ids.add(mid)
        record = custodians["members"][mid]
        if (not isinstance(record, dict) or set(record) != {
                "public_key_hex", "organization_id", "domain_id", "status"
        } or not is_hex(record.get("public_key_hex"), 64) or
                record.get("status") != "active" or
                not isinstance(record.get("organization_id"), str) or
                not record["organization_id"] or
                not isinstance(record.get("domain_id"), str) or
                not record["domain_id"]):
            errors.append(f"invalid_or_revoked_custodian:{index}")
            continue
        org, domain, key = record["organization_id"], record["domain_id"], record["public_key_hex"]
        if org in orgs or domain in domains or key in keys:
            errors.append(f"overlapping_custody:{index}")
            continue
        orgs.add(org)
        domains.add(domain)
        keys.add(key)
        if copy["chain"] != chain or canonical_hash(copy["chain"]) != head:
            errors.append(f"missing_or_divergent_archive:{index}")
            continue
        statement = {
            "schema": STATEMENT_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "chain_sha256": head,
            "first_sequence": chain_pin["first_sequence"],
            "last_sequence": chain_pin["last_sequence"],
            "trust_sha256": canonical_hash(custodians),
            "custodian_id": mid,
            "decision": "HOLD", "authorization": "DENY",
        }
        if (not is_hex(copy.get("signature_ed25519_hex"), 128) or
                verify_signature(key, copy["signature_ed25519_hex"], statement) is not None):
            errors.append(f"invalid_custody_signature:{index}")
            continue
        valid += 1
    if valid < independent_pin["minimum_custodians"]:
        errors.append("insufficient_independent_retention")
    return verdict(errors, len(chain["entries"]) if not errors else 0, valid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("chain", "chain-pin", "witness-trust", "v45-evidence",
                 "archive", "custodians", "independent-pin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def load(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_input")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = assess(*(load(getattr(args, name.replace("-", "_"))) for name in (
            "chain", "chain-pin", "witness-trust", "v45-evidence",
            "archive", "custodians", "independent-pin")))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["custody_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
