#!/usr/bin/env python3
"""GO-20 v22: read-only and reproducible technical assessment receipt.

The receipt is UNTRUSTED, unsigned and never a release decision. Verification
recomputes v21 checks from independently supplied evidence, not from the
receipt's claimed status or from hashes alone.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, unique_pairs
from pr_multiround_assessor import assess, verdict

RECEIPT_SCHEMA = "palaco.go20-assessment-receipt.v1"
EVIDENCE_KEYS = (
    "roundbook", "audit_trust", "witness_trust",
    "logbook", "external_pins", "baseline",
)
MAX_INPUT_BYTES = 8 * 1024 * 1024


def safe_assess(inputs: object) -> dict:
    if not isinstance(inputs, dict) or set(inputs) != set(EVIDENCE_KEYS):
        return verdict(["invalid_assessment_input_set"])
    try:
        return assess(*(inputs[key] for key in EVIDENCE_KEYS))
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError) as exc:
        return verdict(["malformed_nested_evidence:" + type(exc).__name__])


def construct_receipt(inputs: object) -> dict:
    if not isinstance(inputs, dict) or set(inputs) != set(EVIDENCE_KEYS):
        raise ValueError("invalid_assessment_input_set")
    encoded = canonical_hash(inputs)
    report = safe_assess(inputs)
    # This digest is an integrity checksum, not an independent signature.
    body = {
        "schema": RECEIPT_SCHEMA,
        "input_sha256": encoded,
        "input_component_sha256": {
            key: canonical_hash(inputs[key]) for key in EVIDENCE_KEYS
        },
        "assessment": report,
        "independently_attested": False,
    }
    return {**body, "receipt_sha256": canonical_hash(body)}


def verify_receipt(receipt: object, inputs: object) -> dict:
    failures: list[str] = []
    if not isinstance(receipt, dict) or set(receipt) != {
        "schema", "input_sha256", "input_component_sha256",
        "assessment", "independently_attested", "receipt_sha256"
    } or receipt.get("schema") != RECEIPT_SCHEMA:
        failures.append("invalid_receipt_schema")
    if not isinstance(inputs, dict) or set(inputs) != set(EVIDENCE_KEYS):
        failures.append("invalid_independent_inputs")
    if failures:
        return receipt_verdict(failures)
    try:
        expected = construct_receipt(inputs)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        return receipt_verdict(["invalid_input_encoding:" + type(exc).__name__])
    if receipt.get("independently_attested") is not False:
        failures.append("forged_independence_claim")
    if receipt.get("input_sha256") != expected["input_sha256"]:
        failures.append("input_digest_mismatch")
    if receipt.get("input_component_sha256") != expected["input_component_sha256"]:
        failures.append("component_coverage_mismatch")
    if receipt.get("assessment") != expected["assessment"]:
        failures.append("assessment_recomputation_mismatch")
    if receipt.get("receipt_sha256") != expected["receipt_sha256"]:
        failures.append("receipt_digest_mismatch")
    if not expected["assessment"]["technical_evidence_valid"]:
        failures.append("technical_assessment_failed")
    if expected["assessment"].get("decision") != "HOLD" or expected["assessment"].get("authorization") != "DENY":
        failures.append("invalid_governance_result")
    return receipt_verdict(failures)


def receipt_verdict(failures: list[str]) -> dict:
    return {
        "schema": "palaco.go20-assessment-receipt-verdict.v1",
        "receipt_valid": not failures,
        "errors": sorted(set(failures)),
        "decision": "HOLD", "authorization": "DENY",
        "external_attestation_verified": False,
    }


def read_json(path: Path) -> object:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input_too_large")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True,
                        help="Independently provided mapping of all six v21 inputs")
    parser.add_argument("--verify-receipt", type=Path,
                        help="Recompute an existing untrusted receipt")
    args = parser.parse_args()
    try:
        inputs = read_json(args.inputs)
        if args.verify_receipt is not None:
            output = verify_receipt(read_json(args.verify_receipt), inputs)
            ok = output["receipt_valid"]
        else:
            output = construct_receipt(inputs)
            ok = output["assessment"]["technical_evidence_valid"]
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError) as exc:
        output = receipt_verdict(["invalid_input:" + type(exc).__name__])
        ok = False
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
