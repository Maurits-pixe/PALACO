#!/usr/bin/env python3
"""GO-20 v56: offline independently witnessed revocation checkpoint receipts.

A complete v55 history is reverified. Every signed revocation epoch must have
a pinned quorum of archival custody receipts for an identical exact copy.
Signatures bind each epoch, its prior hash, view hash and externally anchored
custodian keys. This NEVER probes storage or establishes real publication.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_revocation_history_consensus import assess as assess_v55

SCHEMA = "palaco.go20-revocation-checkpoint-receipts.v1"
TRUST_SCHEMA = "palaco.go20-revocation-archive-custodian-trust.v1"
PIN_SCHEMA = "palaco.go20-revocation-checkpoint-receipts-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-revocation-checkpoint-custody-statement.v1"


def verdict(errors, epochs=0, receipts=0):
    return {
        "schema": "palaco.go20-revocation-checkpoint-receipts-verdict.v1",
        "receipt_evidence_valid": not errors,
        "epochs_verified": epochs,
        "receipts_verified": receipts,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "remote_storage_verified": False,
        "publication_performed": False,
        "missing_history_recovered": False,
        "revocation_enforced_in_production": False,
        "trust_registry_promoted": False,
        "failover_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess(v55_sources, custody, trust, independent_pin):
    try:
        for item in (v55_sources, custody, trust, independent_pin):
            validate_shape(item)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    sources = {"left", "left_pin", "right", "right_pin", "external", "v54_sources"}
    if not isinstance(v55_sources, dict) or set(v55_sources) != sources:
        return verdict(["invalid_v55_sources"])
    if (not isinstance(custody, dict) or set(custody) != {"schema", "epochs"} or
            custody.get("schema") != SCHEMA or
            not isinstance(custody.get("epochs"), list) or
            not 2 <= len(custody["epochs"]) <= 4):
        return verdict(["invalid_custody_epochs"])
    if (not isinstance(trust, dict) or set(trust) != {"schema", "custodians"} or
            trust.get("schema") != TRUST_SCHEMA or
            not isinstance(trust.get("custodians"), dict) or
            not 3 <= len(trust["custodians"]) <= 7):
        return verdict(["invalid_custodian_trust"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "view_sha256", "head_sha256", "trust_sha256",
            "first_epoch", "last_epoch", "quorum"
    } or independent_pin.get("schema") != PIN_SCHEMA or
            any(not is_hex(independent_pin.get(k), 64) for k in (
                "view_sha256", "head_sha256", "trust_sha256")) or
            any(type(independent_pin.get(k)) is not int for k in (
                "first_epoch", "last_epoch", "quorum")) or
            independent_pin["first_epoch"] < 1 or
            independent_pin["last_epoch"] != independent_pin["first_epoch"] + len(custody["epochs"]) - 1 or
            not 2 <= independent_pin["quorum"] <= len(trust["custodians"])):
        return verdict(["invalid_independent_custody_pin"])
    if (canonical_hash(trust) != independent_pin["trust_sha256"] or
            canonical_hash(v55_sources["left"]) != independent_pin["view_sha256"] or
            canonical_hash(v55_sources["external"]) != independent_pin["head_sha256"]):
        return verdict(["independent_custody_anchor_mismatch"])
    try:
        v = assess_v55(*(v55_sources[k] for k in (
            "left", "left_pin", "right", "right_pin", "external", "v54_sources")))
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["malformed_v55:" + type(exc).__name__])
    if not v["revocation_history_valid"]:
        return verdict(["v55:" + e for e in v["errors"]])
    history = v55_sources["left"]["epochs"]
    if (len(history) != len(custody["epochs"]) or
            independent_pin["first_epoch"] != history[0]["epoch"] or
            independent_pin["last_epoch"] != history[-1]["epoch"]):
        return verdict(["missing_or_rollback_epoch"])
    errors, accepted, signed = [], 0, 0
    for index, record in enumerate(custody["epochs"]):
        expected = history[index]
        if (not isinstance(record, dict) or set(record) != {
                "epoch", "checkpoint", "receipts"
        } or type(record.get("epoch")) is not int or
                record["epoch"] != expected["epoch"] or
                not isinstance(record.get("checkpoint"), dict) or
                not isinstance(record.get("receipts"), list) or
                not 2 <= len(record["receipts"]) <= 7):
            errors.append(f"missing_checkpoint_or_receipts:{index}")
            continue
        if (record["checkpoint"] != expected or
                canonical_hash(record["checkpoint"]) != canonical_hash(expected)):
            errors.append(f"divergent_checkpoint_copy:{index}")
            continue
        used, orgs, domains, keys = set(), set(), set(), set()
        count = 0
        for j, item in enumerate(record["receipts"]):
            if (not isinstance(item, dict) or set(item) != {
                    "custodian_id", "signature_ed25519_hex"
            } or not isinstance(item.get("custodian_id"), str) or
                    item["custodian_id"] not in trust["custodians"] or
                    item["custodian_id"] in used):
                errors.append(f"duplicate_or_unknown_custodian:{index}:{j}")
                continue
            cid = item["custodian_id"]
            used.add(cid)
            member = trust["custodians"][cid]
            if (not isinstance(member, dict) or set(member) != {
                    "public_key_hex", "organization_id", "domain_id", "status"
            } or not is_hex(member.get("public_key_hex"), 64) or
                    member.get("status") != "active" or
                    not isinstance(member.get("organization_id"), str) or
                    not member["organization_id"] or
                    not isinstance(member.get("domain_id"), str) or
                    not member["domain_id"]):
                errors.append(f"invalid_custodian:{index}:{cid}")
                continue
            org, domain, key = (member["organization_id"], member["domain_id"],
                                member["public_key_hex"])
            if org in orgs or domain in domains or key in keys:
                errors.append(f"overlapping_custody:{index}:{cid}")
                continue
            orgs.add(org)
            domains.add(domain)
            keys.add(key)
            statement = {
                "schema": STATEMENT_SCHEMA,
                "repository": "Maurits-pixe/PALACO",
                "epoch": expected["epoch"],
                "checkpoint_sha256": canonical_hash(expected),
                "previous_sha256": expected["previous_sha256"],
                "history_sha256": independent_pin["view_sha256"],
                "head_sha256": independent_pin["head_sha256"],
                "trust_sha256": independent_pin["trust_sha256"],
                "custodian_id": cid,
                "decision": "HOLD", "authorization": "DENY",
            }
            if (not is_hex(item.get("signature_ed25519_hex"), 128) or
                    verify_signature(key, item["signature_ed25519_hex"], statement)
                    is not None):
                errors.append(f"invalid_custody_signature:{index}:{cid}")
                continue
            count += 1
        signed += count
        if count < independent_pin["quorum"]:
            errors.append(f"missing_publication_receipts:{index}")
        else:
            accepted += 1
    return verdict(errors, accepted, signed)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    names = ("v55-evidence", "custody", "custodian-trust", "independent-pin")
    for n in names:
        p.add_argument("--" + n, type=Path, required=True)
    args = p.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_evidence_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        output = assess(*(read(getattr(args, n.replace("-", "_"))) for n in names))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        output = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if output["receipt_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
