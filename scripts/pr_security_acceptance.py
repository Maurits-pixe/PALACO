#!/usr/bin/env python3
"""GO-20 v27: offline consolidated security acceptance receipt.

Recomputes the entire v17-v26 governance verification chain from independent
inputs. The receipt is unsigned and advisory, never release authorization.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, unique_pairs
from pr_governance_hardening import harden, read, validate_shape

SCHEMA = "palaco.go20-security-acceptance.v1"
VERDICT_SCHEMA = "palaco.go20-security-acceptance-verdict.v1"
INPUT_NAMES = ("history", "independent_pin", "controller_trust")
REQUIRED_GATES = (
    "bounded_evidence",
    "signed_governance_chain",
    "independent_anchor_binding",
    "reviewer_role_separation",
    "signed_audit_and_witness_history",
    "release_prohibition",
)


def reject(errors: list[str]) -> dict:
    return {
        "schema": VERDICT_SCHEMA,
        "acceptance_valid": False,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False,
    }


def construct(inputs: object) -> dict:
    if not isinstance(inputs, dict) or set(inputs) != set(INPUT_NAMES):
        raise ValueError("invalid_input_coverage")
    for source in inputs.values():
        validate_shape(source)
    evaluation = harden(*(inputs[key] for key in INPUT_NAMES))
    good = evaluation["evidence_valid"] is True
    gates = {key: good for key in REQUIRED_GATES}
    report = {
        "schema": SCHEMA,
        "repository": "Maurits-pixe/PALACO",
        "input_sha256": canonical_hash(inputs),
        "input_component_sha256": {
            key: canonical_hash(inputs[key]) for key in INPUT_NAMES
        },
        "verification": evaluation,
        "acceptance_gates": gates,
        "technical_acceptance": good and all(gates.values()),
        "independently_attested": False,
        "decision": "HOLD",
        "authorization": "DENY",
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }
    return {**report, "report_sha256": canonical_hash(report)}


def verify(report: object, inputs: object) -> dict:
    if not isinstance(report, dict):
        return reject(["invalid_report"])
    try:
        expected = construct(inputs)
    except (AttributeError, TypeError, ValueError, OverflowError,
            KeyError, IndexError, MemoryError, RecursionError) as exc:
        return reject(["invalid_independent_inputs:" + type(exc).__name__])
    errors = []
    if set(report) != set(expected) or report.get("schema") != SCHEMA:
        errors.append("invalid_report_schema")
    for field in ("repository", "input_sha256", "input_component_sha256",
                  "verification", "acceptance_gates", "technical_acceptance",
                  "independently_attested", "decision", "authorization",
                  "release_authorized", "merge_authorized",
                  "deployment_authorized", "production_commit_performed",
                  "report_sha256"):
        if report.get(field) != expected[field] or type(report.get(field)) is not type(expected[field]):
            errors.append("report_mismatch:" + field)
    if not expected["technical_acceptance"]:
        errors.append("technical_gates_failed")
    return {
        "schema": VERDICT_SCHEMA,
        "acceptance_valid": not errors,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--independent-pin", type=Path, required=True)
    parser.add_argument("--controller-trust", type=Path, required=True)
    parser.add_argument("--verify-report", type=Path)
    args = parser.parse_args()
    try:
        inputs = {
            "history": read(args.history),
            "independent_pin": read(args.independent_pin),
            "controller_trust": read(args.controller_trust),
        }
        if args.verify_report is None:
            output = construct(inputs)
            valid = output["technical_acceptance"]
        else:
            report = json.loads(args.verify_report.read_text(encoding="utf-8"),
                                object_pairs_hook=unique_pairs)
            output = verify(report, inputs)
            valid = output["acceptance_valid"]
    except (OSError, UnicodeError, TypeError, ValueError, OverflowError,
            RecursionError, MemoryError, KeyError) as exc:
        output = reject(["invalid_input:" + type(exc).__name__])
        valid = False
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
