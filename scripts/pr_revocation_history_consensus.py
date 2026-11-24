#!/usr/bin/env python3
"""GO-20 v55: signed append-only historical key revocation snapshots.

Every submitted observer view contains a bounded, hash-linked sequence of
revocation sets. The sets are monotonically cumulative, individually signed
by independent Ed25519 witnesses and bound to a separately pinned head.
Both views must agree exactly. The final revocation set must equal the
complete v54 revocation evidence. No trust changes or writes are performed.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_attestation_chain import verify_signature
from pr_custodian_rotation_witnesses import assess as assess_v54, REVOKE_SCHEMA

SCHEMA = "palaco.go20-revocation-history.v1"
PIN_SCHEMA = "palaco.go20-revocation-history-pin.v1"
VIEW_SCHEMA = "palaco.go20-revocation-history-observer-view.v1"
STATEMENT_SCHEMA = "palaco.go20-revocation-history-witness-statement.v1"
ZERO = "0" * 64


def verdict(errors, epochs=0, signatures=0):
    return {
        "schema": "palaco.go20-revocation-history-verdict.v1",
        "revocation_history_valid": not errors,
        "epochs_verified": epochs,
        "signatures_verified": signatures,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "revocation_enforced_in_production": False,
        "trust_registry_promoted": False,
        "history_restored": False,
        "failover_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def record_set(records):
    if not isinstance(records, list) or len(records) > 30:
        raise ValueError("invalid_records")
    seen = set()
    for entry in records:
        if (not isinstance(entry, dict) or set(entry) != {
                "custodian_id", "public_key_hex", "effective_round"
        } or not isinstance(entry.get("custodian_id"), str) or
                not entry["custodian_id"] or
                not is_hex(entry.get("public_key_hex"), 64) or
                type(entry.get("effective_round")) is not int or
                entry["effective_round"] < 1):
            raise ValueError("invalid_revocation")
        identity = (entry["custodian_id"], entry["public_key_hex"])
        if identity in seen:
            raise ValueError("duplicate_revocation")
        seen.add(identity)
    return {canonical_hash(entry) for entry in records}


def verify_view(view, pin, trust, external):
    if (not isinstance(view, dict) or set(view) != {"schema", "epochs"} or
            view.get("schema") != VIEW_SCHEMA or
            not isinstance(view.get("epochs"), list) or
            not 2 <= len(view["epochs"]) <= 4):
        return ["invalid_observer_view"], 0, 0
    if (not isinstance(pin, dict) or set(pin) != {
            "schema", "first_epoch", "last_epoch", "view_sha256",
            "final_revocations_sha256"
    } or pin.get("schema") != PIN_SCHEMA or
            type(pin.get("first_epoch")) is not int or pin["first_epoch"] < 1 or
            type(pin.get("last_epoch")) is not int or
            pin["last_epoch"] != pin["first_epoch"] + len(view["epochs"]) - 1 or
            not is_hex(pin.get("view_sha256"), 64) or
            not is_hex(pin.get("final_revocations_sha256"), 64)):
        return ["invalid_observer_pin"], 0, 0
    errors, verified, signed = [], 0, 0
    previous, old_set = ZERO, set()
    for i, entry in enumerate(view["epochs"]):
        if (not isinstance(entry, dict) or set(entry) != {
                "epoch", "previous_sha256", "revocations", "signatures"
        } or type(entry.get("epoch")) is not int or
                entry["epoch"] != pin["first_epoch"] + i or
                not is_hex(entry.get("previous_sha256"), 64) or
                not isinstance(entry.get("revocations"), dict) or
                set(entry["revocations"]) != {"schema", "entries"} or
                entry["revocations"].get("schema") != REVOKE_SCHEMA or
                not isinstance(entry.get("signatures"), list) or
                not 2 <= len(entry["signatures"]) <= 7):
            errors.append(f"invalid_epoch:{i}")
            continue
        try:
            current_set = record_set(entry["revocations"]["entries"])
        except ValueError as exc:
            errors.append(f"invalid_revocations:{i}:{exc}")
            continue
        if entry["previous_sha256"] != previous:
            errors.append(f"broken_epoch_link:{i}")
        if not old_set <= current_set:
            errors.append(f"revocation_removed_or_rewritten:{i}")
        old_set = current_set
        signed_statement_base = {
            "schema": STATEMENT_SCHEMA, "repository": "Maurits-pixe/PALACO",
            "epoch": entry["epoch"], "previous_sha256": entry["previous_sha256"],
            "revocations_sha256": canonical_hash(entry["revocations"]),
            "witness_trust_sha256": external["trust_sha256"],
            "final_revocations_sha256": external["final_revocations_sha256"],
            "decision": "HOLD", "authorization": "DENY",
        }
        ids, orgs, domains, keys = set(), set(), set(), set()
        count = 0
        for j, record in enumerate(entry["signatures"]):
            if (not isinstance(record, dict) or set(record) != {
                    "witness_id", "signature_ed25519_hex"
            } or not isinstance(record.get("witness_id"), str) or
                    record["witness_id"] not in trust["witnesses"] or
                    record["witness_id"] in ids):
                errors.append(f"duplicate_or_unknown_witness:{i}:{j}")
                continue
            wid = record["witness_id"]
            ids.add(wid)
            member = trust["witnesses"][wid]
            if (not isinstance(member, dict) or set(member) != {
                    "public_key_hex", "organization_id", "domain_id", "status"
            } or not is_hex(member.get("public_key_hex"), 64) or
                    member.get("status") != "active" or
                    not isinstance(member.get("organization_id"), str) or
                    not member["organization_id"] or
                    not isinstance(member.get("domain_id"), str) or
                    not member["domain_id"]):
                errors.append(f"invalid_witness:{i}:{wid}")
                continue
            org, domain, key = (member["organization_id"],
                                member["domain_id"], member["public_key_hex"])
            if org in orgs or domain in domains or key in keys:
                errors.append(f"overlapping_witness_custody:{i}:{wid}")
                continue
            orgs.add(org)
            domains.add(domain)
            keys.add(key)
            stmt = {**signed_statement_base, "witness_id": wid}
            if (not is_hex(record.get("signature_ed25519_hex"), 128) or
                    verify_signature(key, record["signature_ed25519_hex"], stmt)
                    is not None):
                errors.append(f"invalid_witness_signature:{i}:{wid}")
                continue
            count += 1
        signed += count
        if count < external["quorum"]:
            errors.append(f"insufficient_witness_quorum:{i}")
        else:
            verified += 1
        previous = canonical_hash(entry)
    if canonical_hash(view) != pin["view_sha256"]:
        errors.append("observer_view_anchor_mismatch")
    if (canonical_hash(view["epochs"][-1]["revocations"]) !=
            pin["final_revocations_sha256"]):
        errors.append("observer_final_revocations_mismatch")
    return errors, verified, signed


def assess(left, left_pin, right, right_pin, external, v54_sources):
    try:
        for item in (left, left_pin, right, right_pin, external, v54_sources):
            validate_shape(item)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(external, dict) or set(external) != {
            "schema", "trust_sha256", "final_revocations_sha256",
            "expected_view_sha256", "minimum_last_epoch", "quorum"
    } or external.get("schema") != "palaco.go20-revocation-history-independent-head.v1" or
            any(not is_hex(external.get(k), 64) for k in (
                "trust_sha256", "final_revocations_sha256", "expected_view_sha256")) or
            type(external.get("minimum_last_epoch")) is not int or
            external["minimum_last_epoch"] < 2 or
            type(external.get("quorum")) is not int or
            external["quorum"] < 2):
        return verdict(["invalid_independent_head"])
    fields = {"left", "left_pin", "right", "right_pin", "head",
              "testimony", "witness_trust", "revocations", "independent_pin"}
    if not isinstance(v54_sources, dict) or set(v54_sources) != fields:
        return verdict(["invalid_v54_inputs"])
    trust = v54_sources["witness_trust"]
    revocations = v54_sources["revocations"]
    if (not isinstance(trust, dict) or
            not isinstance(trust.get("witnesses"), dict) or
            not 3 <= len(trust["witnesses"]) <= 7 or
            external["quorum"] > len(trust["witnesses"]) or
            canonical_hash(trust) != external["trust_sha256"] or
            canonical_hash(revocations) != external["final_revocations_sha256"]):
        return verdict(["external_revocation_or_trust_anchor_mismatch"])
    try:
        baseline = assess_v54(*(v54_sources[k] for k in (
            "left", "left_pin", "right", "right_pin", "head", "testimony",
            "witness_trust", "revocations", "independent_pin")))
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["malformed_v54:" + type(exc).__name__])
    if not baseline["rotation_evidence_valid"]:
        return verdict(["v54:" + e for e in baseline["errors"]])
    issues, epochs, signatures = [], 0, 0
    for label, view, pin in (("left", left, left_pin), ("right", right, right_pin)):
        errs, count, sigs = verify_view(view, pin, trust, external)
        issues.extend(f"{label}:{err}" for err in errs)
        epochs += count
        signatures += sigs
    if issues:
        return verdict(issues, epochs, signatures)
    if left_pin["first_epoch"] != right_pin["first_epoch"] or left_pin["last_epoch"] != right_pin["last_epoch"]:
        issues.append("observer_epoch_window_mismatch")
    if left_pin["last_epoch"] < external["minimum_last_epoch"]:
        issues.append("history_epoch_rollback")
    a, b = canonical_hash(left), canonical_hash(right)
    if a != b:
        issues.append("contradictory_revocation_histories")
    if a != external["expected_view_sha256"]:
        issues.append("left_external_head_mismatch")
    if b != external["expected_view_sha256"]:
        issues.append("right_external_head_mismatch")
    if (left_pin["final_revocations_sha256"] != external["final_revocations_sha256"] or
            right_pin["final_revocations_sha256"] != external["final_revocations_sha256"]):
        issues.append("historical_revocation_head_mismatch")
    return verdict(issues, epochs, signatures)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("left", "left-pin", "right", "right-pin", "independent-head", "v54-evidence"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_input")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = assess(*(read(getattr(args, n.replace("-", "_"))) for n in (
            "left", "left-pin", "right", "right-pin", "independent-head", "v54-evidence")))
    except (OSError, TypeError, ValueError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["revocation_history_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
