#!/usr/bin/env python3
"""GO-20 v53: independently pinned custody receipt succession and key rotation.

Verify the entire v52 ledger-history receipt package for each of two sequential
rounds. Trust changes require dual-signed Ed25519 rotations and no weakening of
quorum, retention or custodian diversity. Compare two complete observer views
against an externally fixed head. This is offline evidence ONLY, never authority.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_attestation_chain import verify_signature
from pr_ledger_history_receipts import assess as assess_v52

SCHEMA = "palaco.go20-ledger-receipt-succession.v1"
PIN_SCHEMA = "palaco.go20-ledger-receipt-succession-pin.v1"
ROTATION_SCHEMA = "palaco.go20-ledger-receipt-key-rotation.v1"
ZERO = "0" * 64
SOURCE_FIELDS = {"left", "left_pin", "right", "right_pin", "head", "archive", "trust", "external_pin"}
MAX_ROUNDS = 4


def verdict(errors, rounds=0, rotations=0):
    return {
        "schema": "palaco.go20-ledger-receipt-succession-verdict.v1",
        "succession_evidence_valid": not errors,
        "rounds_verified": rounds,
        "rotations_verified": rotations,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "history_restored": False, "archive_published": False,
        "trust_registry_promoted": False, "challenge_reopened": False,
        "failover_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def assess_view(view, pin):
    if (not isinstance(view, dict) or set(view) != {"schema", "rounds", "rotations"} or
            view.get("schema") != SCHEMA or not isinstance(view.get("rounds"), list) or
            not 2 <= len(view["rounds"]) <= MAX_ROUNDS or
            not isinstance(view.get("rotations"), list) or
            len(view["rotations"]) > 15):
        return ["invalid_succession_view"], 0, 0
    if (not isinstance(pin, dict) or set(pin) != {
                "schema", "first_round", "last_round", "first_round_sha256",
                "last_round_sha256", "view_sha256", "minimum_receipts",
                "minimum_ledger_sequence"
            } or pin.get("schema") != PIN_SCHEMA or
            any(type(pin.get(key)) is not int or pin[key] < minimum for key, minimum in (
                ("first_round", 1), ("last_round", 2),
                ("minimum_receipts", 2), ("minimum_ledger_sequence", 2))) or
            pin["last_round"] != pin["first_round"] + len(view["rounds"]) - 1 or
            any(not is_hex(pin.get(key), 64) for key in (
                "first_round_sha256", "last_round_sha256", "view_sha256"))):
        return ["invalid_succession_pin"], 0, 0
    errors, checked, rotated = [], 0, 0
    rotations = {}
    for idx, record in enumerate(view["rotations"]):
        fields = {"round", "custodian_id", "old_public_key_hex", "new_public_key_hex",
                  "old_trust_sha256", "new_trust_sha256",
                  "old_signature_ed25519_hex", "new_signature_ed25519_hex"}
        if (not isinstance(record, dict) or set(record) != fields or
                type(record.get("round")) is not int or
                not isinstance(record.get("custodian_id"), str)):
            errors.append(f"invalid_rotation:{idx}")
            continue
        tag = (record["round"], record["custodian_id"])
        if tag in rotations:
            errors.append(f"duplicate_rotation:{idx}")
        rotations[tag] = record
    used = set()
    prior = None
    for index, item in enumerate(view["rounds"]):
        if (not isinstance(item, dict) or set(item) != {"round", "previous_round_sha256", "sources"} or
                type(item.get("round")) is not int or
                item["round"] != pin["first_round"] + index or
                not is_hex(item.get("previous_round_sha256"), 64) or
                not isinstance(item.get("sources"), dict) or
                set(item["sources"]) != SOURCE_FIELDS):
            errors.append(f"invalid_or_missing_round:{index}")
            prior = None
            continue
        current = item["sources"]
        try:
            v = assess_v52(*(current[name] for name in (
                "left", "left_pin", "right", "right_pin", "head",
                "archive", "trust", "external_pin")))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError,
                OverflowError, RecursionError, MemoryError) as exc:
            errors.append(f"malformed_v52:{index}:{type(exc).__name__}")
            prior = None
            continue
        if not v["archive_evidence_valid"]:
            errors.extend(f"v52:{index}:{e}" for e in v["errors"])
            prior = None
            continue
        checked += 1
        if index == 0 and canonical_hash(item) != pin["first_round_sha256"]:
            errors.append("first_round_anchor_mismatch")
        if index == len(view["rounds"]) - 1 and canonical_hash(item) != pin["last_round_sha256"]:
            errors.append("last_round_anchor_mismatch")
        if (current["external_pin"]["minimum_receipts"] < pin["minimum_receipts"] or
                current["external_pin"]["minimum_last_sequence"] < pin["minimum_ledger_sequence"]):
            errors.append(f"round_retention_floor_downgrade:{index}")
        if prior is None:
            if index == 0 and item["previous_round_sha256"] != ZERO:
                errors.append("invalid_genesis_link")
        else:
            if item["previous_round_sha256"] != canonical_hash(prior):
                errors.append(f"broken_round_link:{index}")
            before = prior["sources"]["trust"]["custodians"]
            after = current["trust"]["custodians"]
            if set(before) != set(after):
                errors.append(f"custodian_membership_changed:{index}")
            if (current["external_pin"]["minimum_receipts"] <
                    prior["sources"]["external_pin"]["minimum_receipts"] or
                    current["external_pin"]["minimum_last_sequence"] <
                    prior["sources"]["external_pin"]["minimum_last_sequence"]):
                errors.append(f"quorum_or_ledger_floor_downgrade:{index}")
            if canonical_hash(current["left"]) != canonical_hash(prior["sources"]["left"]):
                errors.append(f"history_changed_during_receipt_succession:{index}")
            for mid in before.keys() & after.keys():
                old, new = before[mid]["public_key_hex"], after[mid]["public_key_hex"]
                tag = (item["round"], mid)
                record = rotations.get(tag)
                if old == new:
                    if record is not None:
                        errors.append(f"unnecessary_rotation:{index}:{mid}")
                    continue
                used.add(tag)
                if record is None:
                    errors.append(f"missing_dual_signed_rotation:{index}:{mid}")
                    continue
                expected = {"round": item["round"], "custodian_id": mid,
                            "old_public_key_hex": old, "new_public_key_hex": new,
                            "old_trust_sha256": canonical_hash(prior["sources"]["trust"]),
                            "new_trust_sha256": canonical_hash(current["trust"])}
                if any(record.get(k) != val for k, val in expected.items()):
                    errors.append(f"rotation_binding_mismatch:{index}:{mid}")
                    continue
                statement = {"schema": ROTATION_SCHEMA, **expected}
                success = True
                for side, key in (("old", old), ("new", new)):
                    sig = record.get(side + "_signature_ed25519_hex")
                    if not is_hex(sig, 128) or verify_signature(key, sig, statement) is not None:
                        errors.append(f"invalid_rotation_signature:{index}:{mid}:{side}")
                        success = False
                if success:
                    rotated += 1
        prior = item
    if any(tag not in used for tag in rotations):
        errors.append("orphan_rotation")
    if canonical_hash(view) != pin["view_sha256"]:
        errors.append("independent_view_anchor_mismatch")
    return errors, checked, rotated


def assess(left, left_pin, right, right_pin, independent_head):
    try:
        for source in (left, left_pin, right, right_pin, independent_head):
            validate_shape(source)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(independent_head, dict) or set(independent_head) != {
                "schema", "view_sha256", "minimum_round"
            } or independent_head.get("schema") != "palaco.go20-ledger-receipt-head-pin.v1" or
            not is_hex(independent_head.get("view_sha256"), 64) or
            type(independent_head.get("minimum_round")) is not int or
            independent_head["minimum_round"] < 2):
        return verdict(["invalid_independent_head"])
    errors, checked, rotated = [], 0, 0
    for label, view, pin in (("left", left, left_pin), ("right", right, right_pin)):
        issues, count, rotations = assess_view(view, pin)
        errors.extend(f"{label}:{x}" for x in issues)
        checked += count
        rotated += rotations
    if errors:
        return verdict(errors, checked, rotated)
    if (left_pin["first_round"] != right_pin["first_round"] or
            left_pin["last_round"] != right_pin["last_round"]):
        errors.append("round_window_fork")
    if left_pin["last_round"] < independent_head["minimum_round"]:
        errors.append("receipt_head_rollback")
    a, b = canonical_hash(left), canonical_hash(right)
    if a != b:
        errors.append("contradictory_receipt_registers")
    if a != independent_head["view_sha256"]:
        errors.append("left_external_head_mismatch")
    if b != independent_head["view_sha256"]:
        errors.append("right_external_head_mismatch")
    return verdict(errors, checked, rotated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("left", "left-pin", "right", "right-pin", "independent-head")
    for name in names:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = assess(*(read(getattr(args, n.replace("-", "_"))) for n in names))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["succession_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
