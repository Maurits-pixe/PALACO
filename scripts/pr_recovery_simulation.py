#!/usr/bin/env python3
"""GO-20 v34: strictly read-only, in-memory partial-restore simulation.

All segments must match an independently pinned manifest, and the complete
reconstructed history must pass v33 verification. No disk writes, restore,
database access, deployment, or authorization. Independent trust is external.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_observer_recovery import verify_recovery

SCHEMA = "palaco.go20-recovery-segments.v1"
MANIFEST_SCHEMA = "palaco.go20-recovery-segment-manifest.v1"
PIN_SCHEMA = "palaco.go20-recovery-segment-pin.v1"
PARTS = ("v32_pin", "revocations", "inventory", "recovery_pin")
MAX_SEGMENTS = 12


def outcome(errors: list[str], covered: int = 0, history_valid: bool = False) -> dict:
    return {
        "schema": "palaco.go20-recovery-simulation-verdict.v1",
        "simulation_valid": not errors,
        "segments_verified": covered,
        "recovery_evidence_valid": history_valid,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
        "restore_performed": False,
        "write_performed": False,
    }


def simulate(segments: object, manifest: object, independent_pin: object) -> dict:
    try:
        for source in (segments, manifest, independent_pin):
            validate_shape(source)
    except (ValueError, TypeError, RecursionError, MemoryError) as exc:
        return outcome(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(segments, dict) or set(segments) != {"schema", "parts"} or
            segments.get("schema") != SCHEMA or
            not isinstance(segments.get("parts"), list) or
            not 6 <= len(segments["parts"]) <= MAX_SEGMENTS):
        return outcome(["invalid_segment_package"])
    if (not isinstance(manifest, dict) or set(manifest) != {
            "schema", "repository", "segment_sha256", "epoch_count",
            "history_sha256"} or manifest.get("schema") != MANIFEST_SCHEMA or
            manifest.get("repository") != "Maurits-pixe/PALACO" or
            not isinstance(manifest.get("segment_sha256"), dict) or
            type(manifest.get("epoch_count")) is not int or
            not 2 <= manifest["epoch_count"] <= 8 or
            not is_hex(manifest.get("history_sha256"), 64)):
        return outcome(["invalid_recovery_manifest"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "manifest_sha256", "expected_epochs"
    } or independent_pin.get("schema") != PIN_SCHEMA or
            type(independent_pin.get("expected_epochs")) is not int or
            independent_pin["expected_epochs"] != manifest["epoch_count"] or
            not is_hex(independent_pin.get("manifest_sha256"), 64)):
        return outcome(["invalid_independent_manifest_pin"])
    if canonical_hash(manifest) != independent_pin["manifest_sha256"]:
        return outcome(["independent_manifest_mismatch"])
    expected_names = {f"epoch:{i}" for i in range(manifest["epoch_count"])} | set(PARTS)
    if set(manifest["segment_sha256"]) != expected_names or any(
            not is_hex(value, 64) for value in manifest["segment_sha256"].values()):
        return outcome(["incomplete_or_malformed_manifest_coverage"])
    if len(segments["parts"]) != len(expected_names):
        return outcome(["missing_or_extra_restore_segments"])
    contents: dict[str, object] = {}
    errors: list[str] = []
    for i, segment in enumerate(segments["parts"]):
        if (not isinstance(segment, dict) or set(segment) != {"name", "content"} or
                not isinstance(segment.get("name"), str) or
                segment["name"] not in expected_names):
            errors.append(f"invalid_segment:{i}")
            continue
        name = segment["name"]
        if name in contents:
            errors.append("duplicate_segment:" + name)
            continue
        contents[name] = segment["content"]
        try:
            if canonical_hash(segment["content"]) != manifest["segment_sha256"][name]:
                errors.append("segment_digest_mismatch:" + name)
        except (TypeError, ValueError, OverflowError, RecursionError):
            errors.append("invalid_segment_digest:" + name)
    if set(contents) != expected_names:
        errors.append("incomplete_segment_coverage")
    if errors:
        return outcome(errors, len(contents))
    # Construct in memory only; no filesystem or external writes.
    history = {
        "schema": "palaco.go20-observer-anchor-history.v1",
        "epochs": [contents[f"epoch:{i}"] for i in range(manifest["epoch_count"])],
        "rotations": contents["inventory"]["rotations"]
        if isinstance(contents["inventory"], dict) and
        "rotations" in contents["inventory"] else None,
    }
    # The rotation ledger belongs to the recovered history rather than to the
    # v33 checkpoint inventory; it is carried in its own extra segment.
    return _complete_simulation(history, contents, manifest, len(contents))


def _complete_simulation(history: dict, contents: dict, manifest: dict,
                         covered: int) -> dict:
    # This function is intentionally separated so malformed partial packages
    # always fail before the expensive historical cryptographic checks.
    if history["rotations"] is None:
        return outcome(["missing_rotation_ledger"], covered)
    try:
        if canonical_hash(history) != manifest["history_sha256"]:
            return outcome(["reconstructed_history_mismatch"], covered)
        verified = verify_recovery(
            history, contents["v32_pin"], contents["revocations"],
            contents["inventory"], contents["recovery_pin"])
    except (ValueError, TypeError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return outcome(["malformed_reconstruction:" + type(exc).__name__], covered)
    if not verified["recovery_evidence_valid"]:
        return outcome(["recovery:" + error for error in verified["errors"]] or
                       ["recovery_verification_failed"], covered)
    if (verified["decision"] != "HOLD" or verified["authorization"] != "DENY" or
            verified["restore_performed"] is not False):
        return outcome(["underlying_authority_violation"], covered)
    return outcome([], covered, True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("segments", "manifest", "independent-pin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_input")
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        report = simulate(read(args.segments), read(args.manifest),
                          read(args.independent_pin))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        report = outcome(["invalid_input:" + type(exc).__name__])
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["simulation_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
