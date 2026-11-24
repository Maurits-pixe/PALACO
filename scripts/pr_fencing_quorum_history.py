#!/usr/bin/env python3
"""GO-20 v43: independently pinned historic fencing quorum and key custody.

Verify every v42 epoch and dual-signed Ed25519 key rotation; reject
revoked keys, rollback, weakening quorum, and rewritten snapshots.
No online control plane, storage service, promotion or authorization.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_signed_fencing_quorum import verify_quorum

SCHEMA = "palaco.go20-fencing-quorum-history.v1"
PIN_SCHEMA = "palaco.go20-fencing-quorum-history-pin.v1"
REVOKE_SCHEMA = "palaco.go20-fencing-quorum-revocations.v1"
ROTATE_SCHEMA = "palaco.go20-fencing-quorum-key-rotation.v1"
SNAPSHOT_KEYS = {"epoch", "primary", "candidate", "handoff_pin", "transition",
                 "transition_pin", "signed_votes", "trust", "independent_pin"}
MAX_EPOCHS = 6


def verdict(errors, checked=0, rotations=0):
    return {
        "schema": "palaco.go20-fencing-quorum-history-verdict.v1",
        "history_valid": not errors,
        "epochs_verified": checked,
        "rotations_verified": rotations,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "fence_performed": False, "failover_authorized": False,
        "promotion_performed": False, "release_authorized": False,
        "merge_authorized": False, "deployment_authorized": False,
        "production_commit_performed": False,
    }


def verify_history(history, external_pin, revocations):
    try:
        for source in (history, external_pin, revocations):
            validate_shape(source)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(history, dict) or set(history) != {"schema", "snapshots", "rotations"} or
            history["schema"] != SCHEMA or not isinstance(history["snapshots"], list) or
            not 2 <= len(history["snapshots"]) <= MAX_EPOCHS or
            not isinstance(history["rotations"], list) or len(history["rotations"]) > 35):
        return verdict(["invalid_quorum_history"])
    if (not isinstance(external_pin, dict) or set(external_pin) != {
            "schema", "first_epoch", "last_epoch", "first_snapshot_sha256",
            "last_snapshot_sha256", "revocations_sha256", "history_sha256"
    } or external_pin["schema"] != PIN_SCHEMA):
        return verdict(["invalid_external_history_pin"])
    if (not isinstance(revocations, dict) or
            set(revocations) != {"schema", "entries"} or
            revocations["schema"] != REVOKE_SCHEMA or
            not isinstance(revocations["entries"], list) or len(revocations["entries"]) > 64):
        return verdict(["invalid_revocations"])
    first, last = external_pin["first_epoch"], external_pin["last_epoch"]
    if (type(first) is not int or first < 0 or type(last) is not int or
            last != first + len(history["snapshots"]) - 1 or
            any(not is_hex(external_pin[key], 64) for key in (
                "first_snapshot_sha256", "last_snapshot_sha256",
                "revocations_sha256", "history_sha256"))):
        return verdict(["invalid_history_pin_fields"])
    if canonical_hash(revocations) != external_pin["revocations_sha256"]:
        return verdict(["revocation_anchor_mismatch"])
    revoked = {}
    for i, item in enumerate(revocations["entries"]):
        if (not isinstance(item, dict) or set(item) != {"public_key_hex", "effective_epoch"} or
                not is_hex(item.get("public_key_hex"), 64) or
                type(item.get("effective_epoch")) is not int or item["effective_epoch"] < 0 or
                item["public_key_hex"] in revoked):
            return verdict([f"invalid_or_duplicate_revocation:{i}"])
        revoked[item["public_key_hex"]] = item["effective_epoch"]
    errors = []
    verified = 0
    previous = None
    for index, snapshot in enumerate(history["snapshots"]):
        if (not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_KEYS or
                type(snapshot["epoch"]) is not int or snapshot["epoch"] != first + index):
            errors.append(f"invalid_or_skipped_epoch:{index}")
            continue
        if (not isinstance(snapshot["transition"], dict) or
                snapshot["transition"].get("candidate_epoch") != snapshot["epoch"]):
            errors.append(f"transition_epoch_mismatch:{index}")
            continue
        try:
            v = verify_quorum(*(snapshot[name] for name in (
                "primary", "candidate", "handoff_pin", "transition",
                "transition_pin", "signed_votes", "trust", "independent_pin")))
        except (ValueError, TypeError, IndexError, KeyError, AttributeError,
                RecursionError, OverflowError, MemoryError) as exc:
            errors.append(f"malformed_quorum:{index}:{type(exc).__name__}")
            continue
        if not v["quorum_evidence_valid"]:
            errors.extend(f"epoch:{index}:{issue}" for issue in v["errors"])
            continue
        if index == 0 and canonical_hash(snapshot) != external_pin["first_snapshot_sha256"]:
            errors.append("first_snapshot_anchor_mismatch")
        if index == len(history["snapshots"]) - 1 and canonical_hash(snapshot) != external_pin["last_snapshot_sha256"]:
            errors.append("last_snapshot_anchor_mismatch")
        members = snapshot["trust"]["members"]
        for mid, member in members.items():
            key = member["public_key_hex"]
            if key in revoked and snapshot["epoch"] >= revoked[key] and member["status"] == "active":
                errors.append(f"revoked_key_reused:{index}:{mid}")
        if previous is not None:
            before = previous["trust"]["members"]
            if set(before) != set(members):
                errors.append(f"membership_changed:{index}")
            if snapshot["independent_pin"]["minimum_signatures"] < previous["independent_pin"]["minimum_signatures"]:
                errors.append(f"quorum_floor_downgrade:{index}")
            if snapshot["independent_pin"]["minimum_epoch"] < previous["independent_pin"]["minimum_epoch"]:
                errors.append(f"minimum_epoch_downgrade:{index}")
            if (snapshot["transition"]["old_writer_id"] != previous["transition"]["candidate_id"]):
                errors.append(f"handoff_lineage_discontinuity:{index}")
        previous = snapshot
        verified += 1
    if verified != len(history["snapshots"]):
        return verdict(errors, verified)
    rotation_map = {}
    for i, record in enumerate(history["rotations"]):
        if (not isinstance(record, dict) or set(record) != {
                "epoch", "member_id", "old_public_key_hex", "new_public_key_hex",
                "old_trust_sha256", "new_trust_sha256",
                "old_signature_ed25519_hex", "new_signature_ed25519_hex"
        } or type(record.get("epoch")) is not int or
                not isinstance(record.get("member_id"), str)):
            errors.append(f"invalid_rotation:{i}")
            continue
        tag = (record["epoch"], record["member_id"])
        if tag in rotation_map:
            errors.append(f"duplicate_rotation:{i}")
        rotation_map[tag] = record
    used = set()
    rotations_verified = 0
    for i in range(1, len(history["snapshots"])):
        old = history["snapshots"][i-1]
        new = history["snapshots"][i]
        old_members, new_members = old["trust"]["members"], new["trust"]["members"]
        for mid in old_members.keys() & new_members.keys():
            old_key = old_members[mid]["public_key_hex"]
            new_key = new_members[mid]["public_key_hex"]
            tag = (new["epoch"], mid)
            item = rotation_map.get(tag)
            if old_key == new_key:
                if item is not None:
                    errors.append(f"unnecessary_rotation:{i}:{mid}")
                continue
            used.add(tag)
            if item is None:
                errors.append(f"unsigned_key_rotation:{i}:{mid}")
                continue
            expected = {
                "epoch": new["epoch"], "member_id": mid,
                "old_public_key_hex": old_key,
                "new_public_key_hex": new_key,
                "old_trust_sha256": canonical_hash(old["trust"]),
                "new_trust_sha256": canonical_hash(new["trust"]),
            }
            if any(item.get(k) != value for k, value in expected.items()):
                errors.append(f"rotation_binding_mismatch:{i}:{mid}")
                continue
            statement = {"schema": ROTATE_SCHEMA, **expected}
            valid = True
            for side, key in (("old", old_key), ("new", new_key)):
                signature = item[side + "_signature_ed25519_hex"]
                if (not is_hex(signature, 128) or
                        verify_signature(key, signature, statement) is not None):
                    errors.append(f"rotation_signature_invalid:{i}:{mid}:{side}")
                    valid = False
            if valid:
                rotations_verified += 1
    if any(tag not in used for tag in rotation_map):
        errors.append("orphan_rotation")
    if canonical_hash(history) != external_pin["history_sha256"]:
        errors.append("independent_history_mismatch")
    return verdict(errors, verified, rotations_verified)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("history", "independent-pin", "revocations"):
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_file")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        result = verify_history(read(args.history), read(args.independent_pin), read(args.revocations))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["history_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
