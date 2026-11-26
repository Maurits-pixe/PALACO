#!/usr/bin/env python3
"""GO-20 v19: fail-closed cross-witness audit-fork detector.

Offline only. Audits signer and witness signatures against independent
trust stores. Does not create or persist evidence, sign, or authorize.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_signed_audit_checkpoint import verify_checkpoint

SCHEMA = "palaco.go20-witness-evidence.v1"
TRUST_SCHEMA = "palaco.go20-witness-trust.v1"
ATTESTATION_SCHEMA = "palaco.go20-witness-statement.v1"
MAX_BUNDLES = 16
MAX_ATTESTATIONS = 64


def result(errors: list[str], forks: list[str] | None = None, supported: int = 0) -> dict:
    return {
        "schema": "palaco.go20-witness-review.v1",
        "evidence_valid": not errors,
        "fork_detected": bool(forks),
        "conflicting_checkpoint_sha256": sorted(forks or []),
        "independently_endorsed_checkpoint_count": supported,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
    }


def examine_witnesses(evidence: object, audit_trust: object, witness_trust: object,
                      expected_revision: object, minimum_witnesses: object = 2) -> dict:
    errors: list[str] = []
    if type(expected_revision) is not int or expected_revision < 0:
        errors.append("invalid_expected_revision")
    if type(minimum_witnesses) is not int or not 2 <= minimum_witnesses <= 8:
        errors.append("invalid_quorum")
    if not isinstance(evidence, dict) or set(evidence) != {"schema", "bundles", "attestations"} or evidence.get("schema") != SCHEMA:
        return result(errors + ["invalid_witness_evidence"])
    bundles, attestations = evidence["bundles"], evidence["attestations"]
    if (not isinstance(bundles, list) or not 1 <= len(bundles) <= MAX_BUNDLES or
            not isinstance(attestations, list) or not 1 <= len(attestations) <= MAX_ATTESTATIONS):
        return result(errors + ["invalid_evidence_size"])
    if (not isinstance(witness_trust, dict) or set(witness_trust) != {"schema", "keys"} or
            witness_trust.get("schema") != TRUST_SCHEMA or
            not isinstance(witness_trust.get("keys"), dict) or not witness_trust["keys"]):
        return result(errors + ["invalid_witness_trust"])
    keys = witness_trust["keys"]
    for witness_id, record in keys.items():
        if (not isinstance(witness_id, str) or not witness_id or
                not isinstance(record, dict) or set(record) != {"public_key_hex", "status"} or
                not is_hex(record.get("public_key_hex"), 64) or
                record.get("status") not in ("active", "revoked")):
            errors.append("invalid_witness_key_record")
    if errors:
        return result(errors)

    certified: dict[str, dict] = {}
    for index, bundle in enumerate(bundles):
        if not isinstance(bundle, dict) or set(bundle) != {"export", "manifest", "checkpoint"}:
            errors.append(f"invalid_bundle:{index}")
            continue
        verdict = verify_checkpoint(bundle["export"], bundle["manifest"],
                                    bundle["checkpoint"], audit_trust, expected_revision)
        if not verdict["checkpoint_valid"]:
            errors.extend(f"bundle:{index}:{error}" for error in verdict["errors"])
            continue
        payload = bundle["checkpoint"]["payload"]
        if payload["revision"] != expected_revision:
            errors.append(f"revision_mismatch:{index}")
            continue
        h = canonical_hash(payload)
        if h in certified:
            errors.append("duplicate_checkpoint_bundle")
        certified[h] = bundle

    endorsed: dict[str, set[str]] = {h: set() for h in certified}
    witness_choices: dict[str, str] = {}
    seen_records: set[tuple[str, str]] = set()
    for index, att in enumerate(attestations):
        if not isinstance(att, dict) or set(att) != {
            "witness_id", "revision", "checkpoint_payload_sha256", "signature_ed25519_hex"
        }:
            errors.append(f"invalid_attestation:{index}")
            continue
        wid = att["witness_id"]
        hashed = att["checkpoint_payload_sha256"]
        if not isinstance(wid, str) or wid not in keys:
            errors.append(f"unknown_witness:{index}")
            continue
        record = keys[wid]
        if not isinstance(record, dict) or not is_hex(record.get("public_key_hex"), 64):
            errors.append(f"invalid_witness_record:{index}")
            continue
        if record["status"] == "revoked":
            errors.append(f"revoked_witness:{index}")
            continue
        if type(att["revision"]) is not int or att["revision"] != expected_revision:
            errors.append(f"attestation_revision_mismatch:{index}")
            continue
        if not is_hex(hashed, 64) or hashed not in certified:
            errors.append(f"unmatched_checkpoint:{index}")
            continue
        if not is_hex(att["signature_ed25519_hex"], 128):
            errors.append(f"invalid_witness_signature:{index}")
            continue
        statement = {
            "schema": ATTESTATION_SCHEMA,
            "witness_id": wid,
            "revision": expected_revision,
            "checkpoint_payload_sha256": hashed,
        }
        issue = verify_signature(record["public_key_hex"], att["signature_ed25519_hex"], statement)
        if issue:
            errors.append(f"witness_signature:{index}:{issue}")
            continue
        if (wid, hashed) in seen_records:
            errors.append(f"duplicate_witness_attestation:{index}")
            continue
        seen_records.add((wid, hashed))
        if wid in witness_choices and witness_choices[wid] != hashed:
            errors.append(f"witness_equivocation:{wid}")
        witness_choices[wid] = hashed
        endorsed[hashed].add(wid)

    supported = sum(len(group) >= minimum_witnesses for group in endorsed.values())
    fork_hashes = [h for h, group in endorsed.items() if group]
    if len(fork_hashes) > 1:
        errors.append("signed_checkpoint_fork_detected")
    if any(len(group) < minimum_witnesses for group in endorsed.values()):
        errors.append("insufficient_independent_witnesses")
    return result(errors, fork_hashes if len(fork_hashes) > 1 else [], supported)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--audit-trust", type=Path, required=True)
    parser.add_argument("--witness-trust", type=Path, required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--minimum-witnesses", type=int, default=2)
    args = parser.parse_args()
    try:
        def load(path: Path) -> object:
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        out = examine_witnesses(load(args.evidence), load(args.audit_trust),
                                load(args.witness_trust), args.expected_revision,
                                args.minimum_witnesses)
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        out = result(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
