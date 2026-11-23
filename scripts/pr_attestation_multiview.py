#!/usr/bin/env python3
"""GO-20 v30: offline independently witnessed final-attestation fork detection.

Every supplied view is verified using the v29 full-history verifier and
its own externally retained pin. Compares common sequence numbers, signer
identity and key material, plus witnessed rotation statements. It cannot
find an undisclosed fork and does not authorize execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_final_attestation_history import verify_complete_history
from pr_governance_hardening import validate_shape

SCHEMA = "palaco.go20-attestation-multiview.v1"
PIN_SCHEMA = "palaco.go20-attestation-multiview-pin.v1"
MAX_VIEWS = 8
MAX_VIEW_SIZE = 16


def result(errors: list[str], forks: dict[int, set[str]] | None = None,
           checked: int = 0, rotations: int = 0) -> dict:
    divergent = forks or {}
    return {
        "schema": "palaco.go20-attestation-multiview-verdict.v1",
        "views_valid": not errors,
        "fork_detected": bool(divergent),
        "fork_sequences": sorted(divergent),
        "conflicting_attestation_sha256": {
            str(sequence): sorted(digests)
            for sequence, digests in sorted(divergent.items())
        },
        "views_checked": checked,
        "rotation_records_checked": rotations,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def examine_views(package: object, independent_pin: object) -> dict:
    errors: list[str] = []
    try:
        validate_shape(package)
        validate_shape(independent_pin)
    except (ValueError, TypeError, OverflowError) as exc:
        return result(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(package, dict) or set(package) != {"schema", "views"} or
            package.get("schema") != SCHEMA or
            not isinstance(package.get("views"), list) or
            not 2 <= len(package["views"]) <= MAX_VIEWS):
        return result(["invalid_multiview_package"])
    if (not isinstance(independent_pin, dict) or
            set(independent_pin) != {"schema", "views"} or
            independent_pin.get("schema") != PIN_SCHEMA or
            not isinstance(independent_pin["views"], dict)):
        return result(["invalid_independent_multiview_pin"])
    views = package["views"]
    names = [v.get("view_id") if isinstance(v, dict) else None for v in views]
    if (any(not isinstance(name, str) or not name for name in names) or
            len(set(names)) != len(names)):
        return result(["duplicate_or_invalid_view_identity"])
    if set(names) != set(independent_pin["views"]):
        errors.append("independent_view_pin_coverage_mismatch")
    if errors:
        return result(errors)

    history_by_sequence: dict[int, set[str]] = {}
    rotation_by_sequence: dict[int, set[str]] = {}
    signer_keys: dict[str, set[str]] = {}
    witnessed_genesis: set[str] = set()
    validated = 0
    rotations_checked = 0
    for view in views:
        name = view["view_id"]
        if set(view) != {"view_id", "history", "custodian_trust"}:
            errors.append(f"invalid_view:{name}")
            continue
        pin = independent_pin["views"][name]
        if not isinstance(pin, dict):
            errors.append(f"invalid_view_pin:{name}")
            continue
        outcome = verify_complete_history(view["history"], view["custodian_trust"], pin)
        if not outcome["history_valid"]:
            errors.extend(f"view:{name}:{e}" for e in outcome["errors"])
            continue
        history = view["history"]
        entries = history["entries"]
        if len(entries) > MAX_VIEW_SIZE:
            errors.append(f"view_exceeds_limit:{name}")
            continue
        witnessed_genesis.add(pin["genesis_attestation_sha256"])
        for index, entry in enumerate(entries):
            hashed = canonical_hash(entry["envelope"])
            history_by_sequence.setdefault(index, set()).add(hashed)
            signer_id = entry["envelope"]["signer_key_id"]
            signer_pub = view["custodian_trust"]["keys"][signer_id]["public_key_hex"]
            signer_keys.setdefault(signer_id, set()).add(signer_pub)
        for rotation in history["rotations"]:
            seq = rotation["transition_sequence"]
            rotation_by_sequence.setdefault(seq, set()).add(canonical_hash(rotation))
            rotations_checked += 1
        validated += 1

    if validated != len(views):
        return result(errors or ["insufficient_verified_views"], checked=validated,
                      rotations=rotations_checked)
    if len(witnessed_genesis) > 1:
        errors.append("conflicting_genesis_anchors")
    if any(len(material) > 1 for material in signer_keys.values()):
        errors.append("signer_key_identity_conflict")
    forks = {seq: hashes for seq, hashes in history_by_sequence.items() if len(hashes) > 1}
    if forks:
        errors.append("conflicting_signed_attestations")
    if any(len(hashes) > 1 for hashes in rotation_by_sequence.values()):
        errors.append("conflicting_signed_rotations")
    # A shorter valid view can be a genuine historical prefix of another
    # valid view, provided all overlapping attestations/rotations agree.
    return result(errors, forks, validated, rotations_checked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--views", type=Path, required=True)
    parser.add_argument("--independent-pins", type=Path, required=True)
    args = parser.parse_args()
    try:
        def load(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_evidence")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        out = examine_views(load(args.views), load(args.independent_pins))
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError,
            KeyError, AttributeError, MemoryError, RecursionError) as exc:
        out = result(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["views_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
