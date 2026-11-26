#!/usr/bin/env python3
"""GO-20 v45: offline, independently signed transparency checkpoint views.

Checks v44 provenance, witness Ed25519 signatures, custody diversity and
equivocation across distinct submitted views. Does not publish to a real
transparency log, gossip with peers, fence systems, or authorize failover.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_signed_revocation_fork import check as check_v44

SCHEMA = "palaco.go20-transparency-checkpoint-views.v1"
TRUST_SCHEMA = "palaco.go20-transparency-witness-trust.v1"
PIN_SCHEMA = "palaco.go20-transparency-checkpoint-pin.v1"
STATEMENT_SCHEMA = "palaco.go20-transparency-witness-statement.v1"
CHECKPOINT_SCHEMA = "palaco.go20-transparency-checkpoint.v1"


def verdict(errors, views=0, signatures=0):
    return {
        "schema": "palaco.go20-transparency-checkpoint-verdict.v1",
        "transparency_evidence_valid": not errors,
        "views_verified": views,
        "signatures_verified": signatures,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "checkpoint_published": False, "fence_performed": False,
        "failover_authorized": False, "promotion_performed": False,
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def assess(left_history, left_pin, right_history, right_pin, revocations,
           signed_register, v44_pin, views, trust, independent_pin):
    try:
        for item in (left_history, left_pin, right_history, right_pin, revocations,
                     signed_register, v44_pin, views, trust, independent_pin):
            validate_shape(item)
    except (ValueError, TypeError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(views, dict) or set(views) != {"schema", "observations"} or
            views.get("schema") != SCHEMA or
            not isinstance(views.get("observations"), list) or
            not 2 <= len(views["observations"]) <= 5):
        return verdict(["invalid_observations"])
    if (not isinstance(trust, dict) or set(trust) != {"schema", "witnesses"} or
            trust.get("schema") != TRUST_SCHEMA or
            not isinstance(trust.get("witnesses"), dict) or
            not 3 <= len(trust["witnesses"]) <= 7):
        return verdict(["invalid_witness_register"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "trust_sha256", "checkpoint_sha256",
            "minimum_sequence", "quorum"
    } or independent_pin.get("schema") != PIN_SCHEMA or
            not is_hex(independent_pin.get("trust_sha256"), 64) or
            not is_hex(independent_pin.get("checkpoint_sha256"), 64) or
            type(independent_pin.get("minimum_sequence")) is not int or
            independent_pin["minimum_sequence"] < 0 or
            type(independent_pin.get("quorum")) is not int or
            not 2 <= independent_pin["quorum"] <= len(trust["witnesses"])):
        return verdict(["invalid_independent_checkpoint_pin"])
    if canonical_hash(trust) != independent_pin["trust_sha256"]:
        return verdict(["witness_trust_anchor_mismatch"])
    base = check_v44(left_history, left_pin, right_history, right_pin,
                     revocations, signed_register, v44_pin)
    if not base["historical_evidence_valid"]:
        return verdict(["v44:" + issue for issue in base["errors"]])
    checked = 0
    votes = 0
    errors = []
    observed = set()
    expected_head = canonical_hash(left_history)
    for index, view in enumerate(views["observations"]):
        if (not isinstance(view, dict) or
                set(view) != {"observer_id", "checkpoint", "signatures"} or
                not isinstance(view.get("observer_id"), str) or
                not view["observer_id"] or
                view["observer_id"] in observed or
                not isinstance(view.get("checkpoint"), dict) or
                not isinstance(view.get("signatures"), list)):
            errors.append(f"invalid_view:{index}")
            continue
        observed.add(view["observer_id"])
        checkpoint = view["checkpoint"]
        if (set(checkpoint) != {"schema", "repository", "sequence",
                "last_epoch", "history_sha256", "revocations_sha256"} or
                checkpoint.get("schema") != CHECKPOINT_SCHEMA or
                checkpoint.get("repository") != "Maurits-pixe/PALACO" or
                type(checkpoint.get("sequence")) is not int or
                checkpoint["sequence"] < independent_pin["minimum_sequence"] or
                type(checkpoint.get("last_epoch")) is not int or
                checkpoint["last_epoch"] < 0 or
                not is_hex(checkpoint.get("history_sha256"), 64) or
                not is_hex(checkpoint.get("revocations_sha256"), 64)):
            errors.append(f"invalid_checkpoint:{index}")
            continue
        checkpoint_hash = canonical_hash(checkpoint)
        if checkpoint_hash != independent_pin["checkpoint_sha256"]:
            errors.append(f"equivocation_or_unpinned_checkpoint:{index}")
        if (checkpoint["history_sha256"] != expected_head or
                checkpoint["last_epoch"] != left_pin["last_epoch"] or
                checkpoint["revocations_sha256"] != canonical_hash(revocations)):
            errors.append(f"checkpoint_history_or_revocation_mismatch:{index}")
        seen_ids, used_orgs, used_domains, used_keys = set(), set(), set(), set()
        valid_votes = 0
        for j, record in enumerate(view["signatures"]):
            if (not isinstance(record, dict) or set(record) != {
                    "witness_id", "signature_ed25519_hex"
            } or not isinstance(record.get("witness_id"), str) or
                    record["witness_id"] not in trust["witnesses"] or
                    record["witness_id"] in seen_ids):
                errors.append(f"unknown_or_duplicate_witness:{index}:{j}")
                continue
            witness_id = record["witness_id"]
            seen_ids.add(witness_id)
            witness = trust["witnesses"][witness_id]
            if (not isinstance(witness, dict) or set(witness) != {
                    "public_key_hex", "organization_id", "domain_id", "status"
            } or not is_hex(witness.get("public_key_hex"), 64) or
                    witness.get("status") != "active" or
                    not isinstance(witness.get("organization_id"), str) or
                    not witness["organization_id"] or
                    not isinstance(witness.get("domain_id"), str) or
                    not witness["domain_id"]):
                errors.append(f"invalid_or_revoked_witness:{index}:{witness_id}")
                continue
            org, domain, key = (witness["organization_id"],
                                witness["domain_id"], witness["public_key_hex"])
            if org in used_orgs or domain in used_domains or key in used_keys:
                errors.append(f"overlapping_witness_custody:{index}:{witness_id}")
                continue
            used_orgs.add(org)
            used_domains.add(domain)
            used_keys.add(key)
            statement = {
                "schema": STATEMENT_SCHEMA,
                "observer_id": view["observer_id"],
                "checkpoint_sha256": checkpoint_hash,
                "trust_sha256": canonical_hash(trust),
                "witness_id": witness_id,
                "decision": "HOLD", "authorization": "DENY",
            }
            if (not is_hex(record.get("signature_ed25519_hex"), 128) or
                    verify_signature(key, record["signature_ed25519_hex"], statement)
                    is not None):
                errors.append(f"invalid_witness_signature:{index}:{witness_id}")
                continue
            valid_votes += 1
        votes += valid_votes
        if valid_votes < independent_pin["quorum"]:
            errors.append(f"insufficient_witness_quorum:{index}")
        else:
            checked += 1
    return verdict(errors, checked, votes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("left-history", "left-pin", "right-history", "right-pin",
             "revocations", "signed-register", "v44-pin", "views",
             "trust", "independent-pin")
    for name in names:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def load(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_input")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result = assess(*(load(getattr(args, n.replace("-", "_"))) for n in names))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["transparency_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
