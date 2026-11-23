#!/usr/bin/env python3
"""GO-20 v32: historical observer anchors, revocations and continuity.

Replays every v31 snapshot (including complete v30 evidence) using externally
supplied immutable endpoints. Rotation approvals and revocations are supplied
as data; their authenticity requires independently provisioned custody data.
No signing, external storage, GitHub approval or execution is performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_observer_anchor_custody import verify_anchors

SCHEMA = "palaco.go20-observer-anchor-history.v1"
PIN_SCHEMA = "palaco.go20-observer-history-pin.v1"
REVOCATION_SCHEMA = "palaco.go20-observer-revocations.v1"
ROTATION_SCHEMA = "palaco.go20-observer-key-rotation.v1"
MAX_EPOCHS = 8


def verdict(errors: list[str], epochs: int = 0, rotations: int = 0) -> dict:
    return {
        "schema": "palaco.go20-observer-anchor-history-verdict.v1",
        "history_valid": not errors,
        "epochs_checked": epochs,
        "rotations_verified": rotations,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def verify_observer_history(history: object, external_pin: object,
                            revocations: object) -> dict:
    try:
        for obj in (history, external_pin, revocations):
            validate_shape(obj)
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(history, dict) or
            set(history) != {"schema", "epochs", "rotations"} or
            history.get("schema") != SCHEMA or
            not isinstance(history.get("epochs"), list) or
            not 2 <= len(history["epochs"]) <= MAX_EPOCHS or
            not isinstance(history.get("rotations"), list) or
            len(history["rotations"]) > 8 * (len(history["epochs"]) - 1)):
        return verdict(["invalid_observer_history"])
    if (not isinstance(external_pin, dict) or set(external_pin) != {
            "schema", "first_epoch", "last_epoch", "first_snapshot_sha256",
            "last_snapshot_sha256", "revocation_register_sha256"
    } or external_pin.get("schema") != PIN_SCHEMA):
        return verdict(["invalid_independent_history_pin"])
    if (not isinstance(revocations, dict) or
            set(revocations) != {"schema", "entries"} or
            revocations.get("schema") != REVOCATION_SCHEMA or
            not isinstance(revocations.get("entries"), list) or
            len(revocations["entries"]) > 64):
        return verdict(["invalid_revocation_register"])
    first = external_pin["first_epoch"]
    last = external_pin["last_epoch"]
    if (type(first) is not int or first < 0 or
            type(last) is not int or last != first + len(history["epochs"]) - 1 or
            any(not is_hex(external_pin[key], 64) for key in (
                "first_snapshot_sha256", "last_snapshot_sha256",
                "revocation_register_sha256"))):
        return verdict(["invalid_history_pin_fields"])
    if canonical_hash(revocations) != external_pin["revocation_register_sha256"]:
        return verdict(["independent_revocation_register_mismatch"])
    revoked: dict[str, int] = {}
    for i, entry in enumerate(revocations["entries"]):
        if (not isinstance(entry, dict) or
                set(entry) != {"public_key_hex", "effective_epoch"} or
                not is_hex(entry.get("public_key_hex"), 64) or
                type(entry.get("effective_epoch")) is not int or
                entry["effective_epoch"] < 0 or
                entry["public_key_hex"] in revoked):
            return verdict([f"invalid_or_duplicate_revocation:{i}"])
        revoked[entry["public_key_hex"]] = entry["effective_epoch"]

    snapshots: list[dict] = []
    errors: list[str] = []
    observer_ids: set[str] | None = None
    for i, snapshot in enumerate(history["epochs"]):
        if not isinstance(snapshot, dict) or set(snapshot) != {
            "epoch", "views", "history_pins", "signed_anchors",
            "observer_trust", "independent_heads"
        } or type(snapshot.get("epoch")) is not int or snapshot["epoch"] != first + i:
            errors.append(f"invalid_or_skipped_epoch:{i}")
            continue
        try:
            v = verify_anchors(
                snapshot["views"], snapshot["history_pins"],
                snapshot["signed_anchors"], snapshot["observer_trust"],
                snapshot["independent_heads"])
        except (ValueError, TypeError, KeyError, IndexError, AttributeError,
                RecursionError, OverflowError, MemoryError) as exc:
            errors.append(f"malformed_epoch:{i}:{type(exc).__name__}")
            continue
        if not v["anchors_valid"]:
            errors.extend(f"epoch:{i}:{issue}" for issue in v["errors"])
        trust = snapshot["observer_trust"]["observers"]
        ids = set(trust)
        if observer_ids is not None and ids != observer_ids:
            errors.append(f"observer_membership_changed:{i}")
        observer_ids = ids
        anchors = {
            anchor["view_id"]: anchor for anchor in snapshot["signed_anchors"]["anchors"]
        }
        if any(anchor["statement"]["epoch"] != snapshot["epoch"]
               for anchor in anchors.values()):
            errors.append(f"observer_epoch_mismatch:{i}")
        for vid, keydata in trust.items():
            key = keydata["public_key_hex"]
            if key in revoked and snapshot["epoch"] >= revoked[key]:
                errors.append(f"revoked_observer_key_used:{i}:{vid}")
        if i == 0 and canonical_hash(snapshot) != external_pin["first_snapshot_sha256"]:
            errors.append("independent_first_snapshot_mismatch")
        if i == len(history["epochs"]) - 1 and canonical_hash(snapshot) != external_pin["last_snapshot_sha256"]:
            errors.append("independent_last_snapshot_mismatch")
        snapshots.append(snapshot)
    if len(snapshots) != len(history["epochs"]):
        return verdict(errors, len(snapshots))
    rotations_by_key: dict[tuple[int, str], dict] = {}
    for j, rotation in enumerate(history["rotations"]):
        if (not isinstance(rotation, dict) or set(rotation) != {
                "epoch", "view_id", "old_public_key_hex", "new_public_key_hex",
                "old_anchor_sha256", "new_anchor_sha256",
                "old_signature_ed25519_hex", "new_signature_ed25519_hex"
        } or type(rotation.get("epoch")) is not int or
                not isinstance(rotation.get("view_id"), str)):
            errors.append(f"invalid_rotation:{j}")
            continue
        tag = (rotation["epoch"], rotation["view_id"])
        if tag in rotations_by_key:
            errors.append(f"duplicate_rotation:{j}")
        rotations_by_key[tag] = rotation

    good_rotations = 0
    for i in range(1, len(snapshots)):
        old = snapshots[i - 1]
        new = snapshots[i]
        old_anchors = {x["view_id"]: x for x in old["signed_anchors"]["anchors"]}
        new_anchors = {x["view_id"]: x for x in new["signed_anchors"]["anchors"]}
        old_trust = old["observer_trust"]["observers"]
        new_trust = new["observer_trust"]["observers"]
        for vid in old_trust:
            if vid not in new_trust or vid not in old_anchors or vid not in new_anchors:
                errors.append(f"missing_observer_at_transition:{i}:{vid}")
                continue
            old_key, new_key = old_trust[vid]["public_key_hex"], new_trust[vid]["public_key_hex"]
            tag = (new["epoch"], vid)
            change = rotations_by_key.get(tag)
            if old_key == new_key:
                if change is not None:
                    errors.append(f"unnecessary_rotation:{i}:{vid}")
            elif change is None:
                errors.append(f"unattested_observer_rotation:{i}:{vid}")
            else:
                expected = {
                    "epoch": new["epoch"], "view_id": vid,
                    "old_public_key_hex": old_key, "new_public_key_hex": new_key,
                    "old_anchor_sha256": canonical_hash(old_anchors[vid]),
                    "new_anchor_sha256": canonical_hash(new_anchors[vid]),
                }
                if any(change.get(k) != value for k, value in expected.items()):
                    errors.append(f"rotation_binding_mismatch:{i}:{vid}")
                statement = {"schema": ROTATION_SCHEMA, **expected}
                valid = True
                for side, key in (("old", old_key), ("new", new_key)):
                    sig = change["%s_signature_ed25519_hex" % side]
                    if not is_hex(sig, 128):
                        valid = False
                        errors.append(f"invalid_rotation_signature:{i}:{vid}:{side}")
                        continue
                    issue = verify_signature(key, sig, statement)
                    if issue:
                        valid = False
                        errors.append(f"rotation_signature:{i}:{vid}:{side}:{issue}")
                if valid and not any(x == f"rotation_binding_mismatch:{i}:{vid}" for x in errors):
                    good_rotations += 1
            if (old_anchors[vid]["statement"]["history_pin_sha256"] !=
                    new_anchors[vid]["statement"]["history_pin_sha256"]):
                # A change of history pin is permitted, but the newer
                # independently verified v30 history must extend the old one.
                old_view = next(v for v in old["views"]["views"] if v["view_id"] == vid)
                new_view = next(v for v in new["views"]["views"] if v["view_id"] == vid)
                older = old_view["history"]["entries"]
                newer = new_view["history"]["entries"]
                if (len(newer) < len(older) or any(
                        canonical_hash(a["envelope"]) != canonical_hash(b["envelope"])
                        for a, b in zip(older, newer))):
                    errors.append(f"attestation_history_rollback_or_fork:{i}:{vid}")
    used = {(history["epochs"][i]["epoch"], vid)
            for i in range(1, len(snapshots))
            for vid in snapshots[i]["observer_trust"]["observers"]
            if (snapshots[i]["observer_trust"]["observers"][vid]["public_key_hex"] !=
                snapshots[i-1]["observer_trust"]["observers"][vid]["public_key_hex"])}
    if any(tag not in used for tag in rotations_by_key):
        errors.append("orphan_rotation")
    return verdict(errors, len(snapshots), good_rotations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--independent-pin", type=Path, required=True)
    parser.add_argument("--revocations", type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("oversize_or_missing_input")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        out = verify_observer_history(read(args.history), read(args.independent_pin),
                                      read(args.revocations))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError, IndexError,
            AttributeError, OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out["history_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
