#!/usr/bin/env python3
"""GO-20 v52: independently pinned Ed25519 ledger-history archive receipts.

Both v51 histories must independently verify and match an external head.
At least two independently controlled archival custodians each sign receipt
for a complete and bitwise identical copy of that validated history, binding
the external head and full chain hash. No authority or live custody claims.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_attestation_chain import verify_signature
from pr_challenge_ledger_history import assess as assess_v51

SCHEMA = "palaco.go20-ledger-history-receipts.v1"
TRUST_SCHEMA = "palaco.go20-ledger-history-custodian-trust.v1"
PIN_SCHEMA = "palaco.go20-ledger-history-receipts-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-ledger-history-archive-receipt.v1"
MAX_RECEIPTS = 5


def verdict(errors, count=0):
    return {
        "schema": "palaco.go20-ledger-history-receipts-verdict.v1",
        "archive_evidence_valid": not errors,
        "receipts_verified": count,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "external_storage_verified": False,
        "missing_history_recovered": False,
        "history_rewritten": False,
        "ledger_promoted": False,
        "challenge_reopened": False,
        "failover_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess(left, left_pin, right, right_pin, head, archive, trust, external_pin):
    try:
        for source in (left, left_pin, right, right_pin, head,
                       archive, trust, external_pin):
            validate_shape(source)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(archive, dict) or set(archive) != {"schema", "receipts"} or
            archive.get("schema") != SCHEMA or
            not isinstance(archive.get("receipts"), list) or
            not 2 <= len(archive["receipts"]) <= MAX_RECEIPTS):
        return verdict(["invalid_archived_receipts"])
    if (not isinstance(trust, dict) or set(trust) != {"schema", "custodians"} or
            trust.get("schema") != TRUST_SCHEMA or
            not isinstance(trust.get("custodians"), dict) or
            not 2 <= len(trust["custodians"]) <= MAX_RECEIPTS):
        return verdict(["invalid_custodian_register"])
    if (not isinstance(external_pin, dict) or set(external_pin) != {
            "schema", "trust_sha256", "history_sha256", "head_sha256",
            "minimum_receipts", "minimum_last_sequence"
    } or external_pin.get("schema") != PIN_SCHEMA or
            any(not is_hex(external_pin.get(key), 64) for key in (
                "trust_sha256", "history_sha256", "head_sha256")) or
            type(external_pin.get("minimum_receipts")) is not int or
            not 2 <= external_pin["minimum_receipts"] <= len(trust["custodians"]) or
            type(external_pin.get("minimum_last_sequence")) is not int or
            external_pin["minimum_last_sequence"] < 2):
        return verdict(["invalid_external_archive_pin"])
    if canonical_hash(trust) != external_pin["trust_sha256"]:
        return verdict(["custodian_trust_substitution"])
    if canonical_hash(head) != external_pin["head_sha256"]:
        return verdict(["independent_head_substitution"])
    if canonical_hash(left) != external_pin["history_sha256"]:
        return verdict(["independent_history_substitution"])
    baseline = assess_v51(left, left_pin, right, right_pin, head)
    if not baseline["history_evidence_valid"]:
        return verdict(["v51:" + e for e in baseline["errors"]])
    if (not isinstance(left_pin, dict) or
            left_pin.get("last_sequence", -1) < external_pin["minimum_last_sequence"]):
        return verdict(["archive_history_rollback"])
    errors = []
    seen_ids, orgs, domains, keys = set(), set(), set(), set()
    verified = 0
    for index, item in enumerate(archive["receipts"]):
        if (not isinstance(item, dict) or set(item) != {
                "custodian_id", "history", "signature_ed25519_hex"
        } or not isinstance(item.get("custodian_id"), str) or
                item["custodian_id"] not in trust["custodians"] or
                item["custodian_id"] in seen_ids or
                not isinstance(item.get("history"), dict)):
            errors.append(f"invalid_or_duplicate_receipt:{index}")
            continue
        mid = item["custodian_id"]
        seen_ids.add(mid)
        record = trust["custodians"][mid]
        if (not isinstance(record, dict) or set(record) != {
                "public_key_hex", "organization_id", "domain_id", "status"
        } or not is_hex(record.get("public_key_hex"), 64) or
                not isinstance(record.get("organization_id"), str) or
                not record["organization_id"] or
                not isinstance(record.get("domain_id"), str) or
                not record["domain_id"] or
                record.get("status") != "active"):
            errors.append(f"invalid_or_revoked_custodian:{index}")
            continue
        org, domain, key = (record["organization_id"], record["domain_id"],
                            record["public_key_hex"])
        if org in orgs or domain in domains or key in keys:
            errors.append(f"overlapping_archive_custody:{index}")
            continue
        orgs.add(org)
        domains.add(domain)
        keys.add(key)
        if item["history"] != left or canonical_hash(item["history"]) != external_pin["history_sha256"]:
            errors.append(f"missing_or_divergent_archive_history:{index}")
            continue
        statement = {
            "schema": STATEMENT_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "custodian_id": mid,
            "history_sha256": external_pin["history_sha256"],
            "head_sha256": external_pin["head_sha256"],
            "first_sequence": left_pin["first_sequence"],
            "last_sequence": left_pin["last_sequence"],
            "trust_sha256": external_pin["trust_sha256"],
            "decision": "HOLD",
            "authorization": "DENY",
        }
        if (not is_hex(item.get("signature_ed25519_hex"), 128) or
                verify_signature(key, item["signature_ed25519_hex"], statement)
                is not None):
            errors.append(f"invalid_archive_signature:{index}")
            continue
        verified += 1
    if verified < external_pin["minimum_receipts"]:
        errors.append("insufficient_independent_history_receipts")
    return verdict(errors, verified)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("left-history", "left-pin", "right-history", "right-pin",
             "independent-head", "archive", "custodians", "external-pin")
    for name in names:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_input_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = assess(*(read(getattr(args, name.replace("-", "_"))) for name in names))
    except (OSError, TypeError, ValueError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["archive_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
