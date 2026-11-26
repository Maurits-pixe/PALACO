#!/usr/bin/env python3
"""GO-20 v21: integrated read-only multi-round audit evidence assessment.

All supplied signed rounds must be cumulative. The first checkpoint is pinned
by an INDEPENDENT baseline; witness log heads are separately pinned. This
does not establish the authenticity or freshness of those external pins.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_continuity import WITNESS_SCHEMA, verify_continuity
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_signed_audit_checkpoint import verify_checkpoint
from pr_witness_transparency import verify_transparency

SCHEMA = "palaco.go20-multiround-evidence.v1"
BASELINE_SCHEMA = "palaco.go20-multiround-baseline.v1"
MAX_ROUNDS = 16


def verdict(errors: list[str], rounds: int = 0, checks: dict | None = None) -> dict:
    return {
        "schema": "palaco.go20-multiround-assessment.v1",
        "technical_evidence_valid": not errors,
        "rounds_checked": rounds,
        "checks": checks or {},
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "production_commit_performed": False,
    }


def assess(roundbook: object, audit_trust: object, witness_trust: object,
           logbook: object, external_pins: object, baseline: object) -> dict:
    errors: list[str] = []
    checks: dict = {}
    if (not isinstance(roundbook, dict) or set(roundbook) != {"schema", "rounds"} or
            roundbook.get("schema") != SCHEMA or
            not isinstance(roundbook.get("rounds"), list) or
            not 2 <= len(roundbook["rounds"]) <= MAX_ROUNDS):
        return verdict(["invalid_roundbook"])
    rounds = roundbook["rounds"]
    if (not isinstance(baseline, dict) or set(baseline) != {
            "schema", "first_revision", "first_payload_sha256",
            "last_revision", "last_payload_sha256"
    } or baseline.get("schema") != BASELINE_SCHEMA):
        return verdict(["invalid_external_baseline"])
    first, last = baseline["first_revision"], baseline["last_revision"]
    if (type(first) is not int or type(last) is not int or
            first < 0 or last != first + len(rounds) - 1 or
            not is_hex(baseline["first_payload_sha256"], 64) or
            not is_hex(baseline["last_payload_sha256"], 64)):
        return verdict(["invalid_external_baseline_fields"])

    hashes: list[str] = []
    for index, bundle in enumerate(rounds):
        if not isinstance(bundle, dict) or set(bundle) != {
            "export", "manifest", "checkpoint"
        }:
            errors.append(f"invalid_bundle:{index}")
            continue
        review = verify_checkpoint(bundle["export"], bundle["manifest"],
                                   bundle["checkpoint"], audit_trust, first + index)
        checks[f"checkpoint:{index}"] = review["checkpoint_valid"]
        if not review["checkpoint_valid"]:
            errors.extend(f"checkpoint:{index}:{e}" for e in review["errors"])
            continue
        payload = bundle["checkpoint"]["payload"]
        if payload["revision"] != first + index:
            errors.append(f"checkpoint_revision_mismatch:{index}")
        hashes.append(canonical_hash(payload))

    if len(hashes) != len(rounds):
        return verdict(errors, len(rounds), checks)
    if hashes[0] != baseline["first_payload_sha256"]:
        errors.append("independent_first_checkpoint_mismatch")
    if hashes[-1] != baseline["last_payload_sha256"]:
        errors.append("independent_last_checkpoint_mismatch")

    for index in range(len(rounds) - 1):
        witness = {"schema": WITNESS_SCHEMA, "revision": first + index,
                   "checkpoint_payload_sha256": hashes[index]}
        review = verify_continuity(rounds[index], rounds[index + 1],
                                   audit_trust, witness)
        checks[f"continuity:{index}"] = review["continuity_valid"]
        errors.extend(f"continuity:{index}:{e}" for e in review["errors"])

    transparency = verify_transparency(logbook, witness_trust, external_pins, first)
    checks["witness_transparency"] = transparency["history_valid"]
    errors.extend("transparency:" + e for e in transparency["errors"])
    if transparency["history_valid"]:
        if not isinstance(logbook, dict) or not isinstance(logbook.get("logs"), list):
            errors.append("invalid_logbook")
        else:
            for index, log in enumerate(logbook["logs"]):
                entries = log.get("entries") if isinstance(log, dict) else None
                if not isinstance(entries, list) or len(entries) != len(hashes):
                    errors.append(f"publication_round_coverage:{index}")
                    continue
                for pos, entry in enumerate(entries):
                    if entry["checkpoint_payload_sha256"] != hashes[pos]:
                        errors.append(f"publication_checkpoint_mismatch:{index}:{pos}")
    return verdict(errors, len(rounds), checks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roundbook", type=Path, required=True)
    parser.add_argument("--audit-trust", type=Path, required=True)
    parser.add_argument("--witness-trust", type=Path, required=True)
    parser.add_argument("--transparency-logbook", type=Path, required=True)
    parser.add_argument("--independent-pins", type=Path, required=True)
    parser.add_argument("--independent-baseline", type=Path, required=True)
    args = parser.parse_args()
    try:
        def load(path: Path):
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        out = assess(load(args.roundbook), load(args.audit_trust),
                     load(args.witness_trust), load(args.transparency_logbook),
                     load(args.independent_pins), load(args.independent_baseline))
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out["technical_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
