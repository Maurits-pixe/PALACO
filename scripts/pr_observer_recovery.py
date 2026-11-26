#!/usr/bin/env python3
"""GO-20 v33: read-only historical retention and recovery proof verifier.

Validates every retained observer epoch against a separately supplied
checkpoint inventory and independently retained exact endpoints, then
re-verifies the complete v32 history. Never restores files or grants access.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import ZERO, canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_observer_anchor_history import verify_observer_history

SCHEMA = "palaco.go20-observer-recovery-inventory.v1"
PIN_SCHEMA = "palaco.go20-observer-recovery-pin.v1"
CHECKPOINT_SCHEMA = "palaco.go20-observer-recovery-checkpoint.v1"
MAX_EPOCHS = 8


def verdict(errors: list[str], checked: int = 0, history_valid: bool = False) -> dict:
    return {
        "schema": "palaco.go20-observer-recovery-verdict.v1",
        "recovery_evidence_valid": not errors,
        "historical_chain_valid": history_valid,
        "checkpoints_verified": checked,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
        "restore_performed": False,
    }


def verify_recovery(restored_history: object, v32_pin: object,
                    revocations: object, inventory: object,
                    independent_pin: object) -> dict:
    try:
        for item in (restored_history, v32_pin, revocations, inventory, independent_pin):
            validate_shape(item)
    except (ValueError, TypeError, RecursionError, OverflowError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(restored_history, dict) or
            not isinstance(restored_history.get("epochs"), list) or
            not 2 <= len(restored_history["epochs"]) <= MAX_EPOCHS):
        return verdict(["invalid_restored_history"])
    if (not isinstance(inventory, dict) or
            set(inventory) != {"schema", "checkpoints", "history_sha256", "v32_pin_sha256",
                               "revocations_sha256", "repository"} or
            inventory.get("schema") != SCHEMA or
            not isinstance(inventory.get("checkpoints"), list) or
            len(inventory["checkpoints"]) != len(restored_history["epochs"])):
        return verdict(["invalid_checkpoint_inventory"])
    if (not isinstance(independent_pin, dict) or
            set(independent_pin) != {"schema", "inventory_sha256", "first_checkpoint_sha256",
                                    "last_checkpoint_sha256", "last_epoch", "minimum_epochs"} or
            independent_pin.get("schema") != PIN_SCHEMA):
        return verdict(["invalid_independent_recovery_pin"])
    if (type(independent_pin["last_epoch"]) is not int or
            independent_pin["last_epoch"] < 0 or
            type(independent_pin["minimum_epochs"]) is not int or
            independent_pin["minimum_epochs"] < 2 or
            independent_pin["minimum_epochs"] > MAX_EPOCHS or
            len(restored_history["epochs"]) < independent_pin["minimum_epochs"] or
            any(not is_hex(independent_pin[name], 64) for name in
                ("inventory_sha256", "first_checkpoint_sha256", "last_checkpoint_sha256"))):
        return verdict(["invalid_retention_floor_or_anchor"])
    errors = []
    if inventory["repository"] != "Maurits-pixe/PALACO":
        errors.append("repository_mismatch")
    try:
        if canonical_hash(inventory) != independent_pin["inventory_sha256"]:
            errors.append("independent_inventory_mismatch")
        if canonical_hash(restored_history) != inventory["history_sha256"]:
            errors.append("restored_history_mismatch")
        if canonical_hash(v32_pin) != inventory["v32_pin_sha256"]:
            errors.append("v32_pin_mismatch")
        if canonical_hash(revocations) != inventory["revocations_sha256"]:
            errors.append("revocations_mismatch")
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        return verdict(errors + ["unhashable_recovery_evidence:" + type(exc).__name__])
    if any(not is_hex(inventory[name], 64) for name in
           ("history_sha256", "v32_pin_sha256", "revocations_sha256")):
        errors.append("invalid_inventory_digest_encoding")
    try:
        historic = verify_observer_history(restored_history, v32_pin, revocations)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            RecursionError, MemoryError, OverflowError) as exc:
        return verdict(errors + ["malformed_observer_history:" + type(exc).__name__])
    if not historic["history_valid"]:
        errors.extend("history:" + issue for issue in historic["errors"])
    previous = ZERO
    checked = 0
    checkpoints = inventory["checkpoints"]
    for i, checkpoint in enumerate(checkpoints):
        if (not isinstance(checkpoint, dict) or set(checkpoint) != {
                "schema", "epoch", "snapshot_sha256", "previous_checkpoint_sha256",
                "checkpoint_sha256"} or checkpoint.get("schema") != CHECKPOINT_SCHEMA):
            errors.append(f"invalid_checkpoint:{i}")
            continue
        source = restored_history["epochs"][i]
        payload = {key: value for key, value in checkpoint.items()
                   if key != "checkpoint_sha256"}
        if (type(checkpoint["epoch"]) is not int or
                not isinstance(source, dict) or
                checkpoint["epoch"] != source.get("epoch") or
                checkpoint["previous_checkpoint_sha256"] != previous or
                not is_hex(checkpoint["snapshot_sha256"], 64) or
                not is_hex(checkpoint["checkpoint_sha256"], 64) or
                checkpoint["snapshot_sha256"] != canonical_hash(source) or
                checkpoint["checkpoint_sha256"] != canonical_hash(payload)):
            errors.append(f"checkpoint_integrity_failure:{i}")
        previous = canonical_hash(payload)
        checked += 1
    if checkpoints and isinstance(checkpoints[0], dict) and (
            checkpoints[0].get("checkpoint_sha256") !=
            independent_pin["first_checkpoint_sha256"]):
        errors.append("first_checkpoint_anchor_mismatch")
    if previous != independent_pin["last_checkpoint_sha256"]:
        errors.append("last_checkpoint_anchor_mismatch")
    if restored_history["epochs"][-1].get("epoch") != independent_pin["last_epoch"]:
        errors.append("recovery_epoch_rollback")
    return verdict(errors, checked, historic["history_valid"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("restored-history", "v32-pin", "revocations",
                 "inventory", "independent-recovery-pin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_file")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = verify_recovery(read(args.restored_history), read(args.v32_pin),
                              read(args.revocations), read(args.inventory),
                              read(args.independent_recovery_pin))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError, IndexError,
            AttributeError, RecursionError, OverflowError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out["recovery_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
