#!/usr/bin/env python3
"""GO-20 v64: independent signed historical custody checkpoints.

Each v63 succession snapshot needs an identical, independently witnessed
publication statement in two supplied views. Effective custodian-key
revocations and an externally pinned publication head are checked. Offline
signatures are evidence claims, NOT proof of actual network publication.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_head_custody_succession import assess as assess_v63

SCHEMA = "palaco.go20-historical-custody-checkpoints.v1"
TRUST_SCHEMA = "palaco.go20-publication-witness-trust.v1"
REVOKE_SCHEMA = "palaco.go20-archive-custodian-revocations.v1"
PIN_SCHEMA = "palaco.go20-publication-checkpoint-independent-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-publication-checkpoint-witness-statement.v1"


def verdict(errors, checkpoints=0, signatures=0):
    return {
        "schema": "palaco.go20-historical-custody-checkpoint-verdict.v1",
        "checkpoint_evidence_valid": not errors,
        "checkpoints_verified": checkpoints,
        "witness_signatures_verified": signatures,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "live_publication_verified": False, "external_custody_verified": False,
        "storage_access_verified": False, "revocation_enforced_in_production": False,
        "recovery_authorized": False, "history_restored": False,
        "merge_authorized": False, "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess(sources, left, right, trust, revocations, pin):
    try:
        for obj in (sources, left, right, trust, revocations, pin):
            validate_shape(obj)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(sources, dict) or set(sources) != {
            "left", "left_pin", "right", "right_pin", "head"
    } or not isinstance(trust, dict) or set(trust) != {"schema", "members"} or
            trust.get("schema") != TRUST_SCHEMA or
            not isinstance(trust.get("members"), dict) or
            not 2 <= len(trust["members"]) <= 5):
        return verdict(["invalid_source_or_witness_registry"])
    if (not isinstance(revocations, dict) or set(revocations) != {
            "schema", "entries"
    } or revocations.get("schema") != REVOKE_SCHEMA or
            not isinstance(revocations.get("entries"), list) or
            len(revocations["entries"]) > 30):
        return verdict(["invalid_revocation_registry"])
    if (not isinstance(pin, dict) or set(pin) != {
            "schema", "v63_sha256", "trust_sha256", "revocations_sha256",
            "left_sha256", "right_sha256", "minimum_snapshot", "quorum"
    } or pin.get("schema") != PIN_SCHEMA or
            any(not is_hex(pin.get(k), 64) for k in (
                "v63_sha256", "trust_sha256", "revocations_sha256",
                "left_sha256", "right_sha256")) or
            type(pin.get("minimum_snapshot")) is not int or
            pin["minimum_snapshot"] < 2 or
            type(pin.get("quorum")) is not int or
            not 2 <= pin["quorum"] <= len(trust["members"])):
        return verdict(["invalid_external_checkpoint_pin"])
    if (canonical_hash(sources) != pin["v63_sha256"] or
            canonical_hash(trust) != pin["trust_sha256"] or
            canonical_hash(revocations) != pin["revocations_sha256"] or
            canonical_hash(left) != pin["left_sha256"] or
            canonical_hash(right) != pin["right_sha256"]):
        return verdict(["independent_checkpoint_anchor_mismatch"])
    try:
        previous = assess_v63(*(sources[k] for k in (
            "left", "left_pin", "right", "right_pin", "head")))
    except (KeyError, ValueError, TypeError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["malformed_v63:" + type(exc).__name__])
    if not previous["custody_succession_valid"]:
        return verdict(["v63:" + e for e in previous["errors"]])
    original = sources["left"]["snapshots"]
    if original[-1]["snapshot"] < pin["minimum_snapshot"]:
        return verdict(["snapshot_rollback"])
    errors, revoked = [], set()
    for i, item in enumerate(revocations["entries"]):
        if (not isinstance(item, dict) or set(item) != {
                "custodian_id", "public_key_hex", "effective_snapshot"
            } or not isinstance(item.get("custodian_id"), str) or
                not item["custodian_id"] or
                not is_hex(item.get("public_key_hex"), 64) or
                type(item.get("effective_snapshot")) is not int or
                not 1 <= item["effective_snapshot"] <= original[-1]["snapshot"]):
            errors.append(f"invalid_revocation:{i}")
            continue
        identity = (item["custodian_id"], item["public_key_hex"])
        if identity in revoked:
            errors.append(f"duplicate_revocation:{i}")
        revoked.add(identity)
    for i, snap in enumerate(original):
        members = snap["sources"]["trust"]["members"]
        for cid, member in members.items():
            if any(isinstance(item, dict) and
                   item.get("custodian_id") == cid and
                   item.get("public_key_hex") == member["public_key_hex"] and
                   type(item.get("effective_snapshot")) is int and
                   item["effective_snapshot"] <= snap["snapshot"]
                   for item in revocations["entries"]):
                errors.append(f"revoked_custodian_reused:{i}:{cid}")
    verified, signed = 0, 0
    for label, view in (("left", left), ("right", right)):
        if (not isinstance(view, dict) or set(view) != {"schema", "checkpoints"} or
                view.get("schema") != SCHEMA or
                not isinstance(view.get("checkpoints"), list) or
                len(view["checkpoints"]) != len(original)):
            errors.append(f"{label}:missing_historical_publications")
            continue
        for i, (record, snap) in enumerate(zip(view["checkpoints"], original)):
            if (not isinstance(record, dict) or set(record) != {
                    "snapshot", "snapshot_sha256", "signatures"
                } or type(record.get("snapshot")) is not int or
                    record["snapshot"] != snap["snapshot"] or
                    record.get("snapshot_sha256") != canonical_hash(snap) or
                    not isinstance(record.get("signatures"), list) or
                    not 2 <= len(record["signatures"]) <= 5):
                errors.append(f"{label}:invalid_checkpoint:{i}")
                continue
            ids, orgs, domains, keys = set(), set(), set(), set()
            count = 0
            for j, item in enumerate(record["signatures"]):
                if (not isinstance(item, dict) or set(item) != {
                        "witness_id", "signature_ed25519_hex"
                    } or not isinstance(item.get("witness_id"), str) or
                        item["witness_id"] not in trust["members"] or
                        item["witness_id"] in ids):
                    errors.append(f"{label}:duplicate_or_unknown_witness:{i}:{j}")
                    continue
                wid = item["witness_id"]
                ids.add(wid)
                member = trust["members"][wid]
                if (not isinstance(member, dict) or set(member) != {
                        "public_key_hex", "organization_id", "domain_id", "status"
                    } or not is_hex(member.get("public_key_hex"), 64) or
                        member.get("status") != "active" or
                        not isinstance(member.get("organization_id"), str) or
                        not member["organization_id"] or
                        not isinstance(member.get("domain_id"), str) or
                        not member["domain_id"]):
                    errors.append(f"{label}:invalid_witness:{i}:{wid}")
                    continue
                org, domain, key = (member["organization_id"], member["domain_id"],
                                    member["public_key_hex"])
                if org in orgs or domain in domains or key in keys:
                    errors.append(f"{label}:overlapping_witness_custody:{i}:{wid}")
                    continue
                orgs.add(org)
                domains.add(domain)
                keys.add(key)
                stmt = {
                    "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
                    "snapshot": snap["snapshot"],
                    "snapshot_sha256": canonical_hash(snap),
                    "previous_sha256": snap["previous_sha256"],
                    "v63_sha256": pin["v63_sha256"],
                    "trust_sha256": pin["trust_sha256"],
                    "revocations_sha256": pin["revocations_sha256"],
                    "witness_id": wid,
                    "decision": "HOLD", "authorization": "DENY",
                }
                if (not is_hex(item.get("signature_ed25519_hex"), 128) or
                        verify_signature(key, item["signature_ed25519_hex"],
                                         stmt) is not None):
                    errors.append(f"{label}:invalid_witness_signature:{i}:{wid}")
                    continue
                count += 1
            signed += count
            if count < pin["quorum"]:
                errors.append(f"{label}:insufficient_publication_witnesses:{i}")
            else:
                verified += 1
    if isinstance(left, dict) and isinstance(right, dict) and (
            canonical_hash(left) != canonical_hash(right)):
        errors.append("split_publication_histories")
    return verdict(errors, verified, signed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("v63-evidence", "left", "right", "witness-trust",
                 "custodian-revocations", "independent-pin"):
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
            "v63-evidence", "left", "right", "witness-trust",
            "custodian-revocations", "independent-pin")))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["checkpoint_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
