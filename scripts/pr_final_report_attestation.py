#!/usr/bin/env python3
"""GO-20 v28: independently pinned, signed final-security-report attestation.

Offline verification only. Cryptographic validity never grants approval,
release, merge, deployment, or production access. Trust and anti-rollback
anchors must be provisioned independently of the untrusted envelope.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_audit_integrity import ZERO, canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import read
from pr_security_acceptance import INPUT_NAMES, verify as verify_acceptance

SCHEMA = "palaco.go20-final-report-attestation.v1"
STATEMENT_SCHEMA = "palaco.go20-final-report-statement.v1"
TRUST_SCHEMA = "palaco.go20-final-report-trust.v1"
PIN_SCHEMA = "palaco.go20-final-report-pin.v1"


def verdict(errors: list[str]) -> dict:
    return {
        "schema": "palaco.go20-final-report-attestation-verdict.v1",
        "attestation_valid": not errors,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "release_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "production_commit_performed": False,
    }


def check_envelope(envelope: object, trust: object, expected_sequence: int,
                   expected_predecessor: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(envelope, dict) or set(envelope) != {
        "statement", "signer_key_id", "signature_ed25519_hex"
    }:
        return ["invalid_attestation_envelope"]
    statement = envelope["statement"]
    if not isinstance(statement, dict) or set(statement) != {
        "schema", "repository", "sequence", "previous_attestation_sha256",
        "report_sha256", "decision", "authorization"
    } or statement.get("schema") != STATEMENT_SCHEMA:
        return ["invalid_attestation_statement"]
    if statement["repository"] != "Maurits-pixe/PALACO":
        errors.append("repository_mismatch")
    if type(statement["sequence"]) is not int or statement["sequence"] != expected_sequence:
        errors.append("attestation_sequence_rollback_or_gap")
    if statement["previous_attestation_sha256"] != expected_predecessor:
        errors.append("predecessor_binding_mismatch")
    if not is_hex(statement["report_sha256"], 64):
        errors.append("invalid_report_digest")
    if statement["decision"] != "HOLD" or statement["authorization"] != "DENY":
        errors.append("unauthorized_attestation_statement")
    signer = envelope["signer_key_id"]
    keys = trust["keys"]
    key = keys.get(signer) if isinstance(signer, str) else None
    if (not isinstance(key, dict) or set(key) != {"public_key_hex", "status", "role"} or
            not is_hex(key.get("public_key_hex"), 64) or
            key.get("status") != "active" or
            key.get("role") != "attestation_custodian"):
        errors.append("untrusted_revoked_or_wrong_role_signer")
    if not is_hex(envelope["signature_ed25519_hex"], 128):
        errors.append("invalid_signature_encoding")
    if not errors:
        issue = verify_signature(key["public_key_hex"],
                                 envelope["signature_ed25519_hex"], statement)
        if issue:
            errors.append("attestation_signature:" + issue)
    return errors


def assess_attestation(envelope: object, report: object, inputs: object,
                       trust: object, external_pin: object,
                       previous_envelope: object = None) -> dict:
    errors: list[str] = []
    if (not isinstance(trust, dict) or set(trust) != {"schema", "keys"} or
            trust.get("schema") != TRUST_SCHEMA or
            not isinstance(trust.get("keys"), dict) or not trust["keys"]):
        return verdict(["invalid_independent_attestation_trust"])
    for signer, key in trust["keys"].items():
        if (not isinstance(signer, str) or not signer or
                not isinstance(key, dict) or set(key) != {"public_key_hex", "status", "role"} or
                not is_hex(key.get("public_key_hex"), 64) or
                key.get("status") not in ("active", "revoked") or
                key.get("role") != "attestation_custodian"):
            errors.append("invalid_attestation_key_record")
    if (not isinstance(external_pin, dict) or set(external_pin) != {
            "schema", "expected_sequence", "previous_attestation_sha256"
    } or external_pin.get("schema") != PIN_SCHEMA):
        return verdict(errors + ["invalid_independent_attestation_pin"])
    sequence = external_pin["expected_sequence"]
    predecessor = external_pin["previous_attestation_sha256"]
    if (type(sequence) is not int or sequence < 0 or
            not is_hex(predecessor, 64) or
            (sequence == 0 and predecessor != ZERO) or
            (sequence > 0 and predecessor == ZERO)):
        return verdict(errors + ["invalid_independent_attestation_pin_fields"])
    if errors:
        return verdict(errors)
    acceptance = verify_acceptance(report, inputs)
    if not acceptance["acceptance_valid"]:
        errors.extend("report:" + issue for issue in acceptance["errors"])
    if not isinstance(report, dict) or not is_hex(report.get("report_sha256"), 64):
        errors.append("invalid_security_report")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("statement"), dict):
        errors.append("invalid_attestation_envelope")
    else:
        if isinstance(report, dict) and envelope["statement"].get("report_sha256") != report.get("report_sha256"):
            errors.append("signed_report_binding_mismatch")
    if sequence == 0:
        if previous_envelope is not None:
            errors.append("unexpected_genesis_predecessor")
    else:
        if previous_envelope is None:
            errors.append("missing_previous_attestation")
        else:
            try:
                if canonical_hash(previous_envelope) != predecessor:
                    errors.append("independent_predecessor_pin_mismatch")
            except (TypeError, ValueError, OverflowError, RecursionError):
                errors.append("invalid_previous_attestation_encoding")
            errors.extend("previous:" + error for error in
                          check_envelope(previous_envelope, trust, sequence - 1,
                                         ZERO if sequence == 1 else
                                         previous_envelope.get("statement", {}).get(
                                             "previous_attestation_sha256")))
            # A pinned earlier head is insufficient alone if this predecessor's
            # own prior link is malformed. For sequence > 1 the predecessor
            # links to an earlier independently stored digest, but the earlier
            # envelope is not supplied here: this is a one-hop verification.
            if sequence > 1:
                prior_statement = (previous_envelope.get("statement")
                                   if isinstance(previous_envelope, dict) else None)
                if (not isinstance(prior_statement, dict) or
                        not is_hex(prior_statement.get("previous_attestation_sha256"), 64) or
                        prior_statement["previous_attestation_sha256"] == ZERO):
                    errors.append("previous_attestation_link_invalid")
    errors.extend(check_envelope(envelope, trust, sequence, predecessor))
    # Keep attestation keys distinct from reviewer and controller keys.
    try:
        forbidden_keys = {
            record["public_key_hex"]
            for record in inputs["controller_trust"]["controllers"].values()
            if isinstance(record, dict) and is_hex(record.get("public_key_hex"), 64)
        }
        for snapshot in inputs["history"]["snapshots"]:
            forbidden_keys.update(
                record["public_key_hex"]
                for record in snapshot["reviewer_trust"]["reviewers"].values()
                if isinstance(record, dict) and is_hex(record.get("public_key_hex"), 64)
            )
        if any(key["public_key_hex"] in forbidden_keys
               for key in trust["keys"].values()):
            errors.append("attestation_key_role_overlap")
    except (TypeError, KeyError, AttributeError, IndexError):
        errors.append("unable_to_check_attestation_role_separation")
    return verdict(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--security-report", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--independent-governance-pin", type=Path, required=True)
    parser.add_argument("--controller-trust", type=Path, required=True)
    parser.add_argument("--attestation-trust", type=Path, required=True)
    parser.add_argument("--independent-attestation-pin", type=Path, required=True)
    parser.add_argument("--previous-attestation", type=Path)
    args = parser.parse_args()
    try:
        def load(path: Path):
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs)
        inputs = {
            "history": read(args.history),
            "independent_pin": read(args.independent_governance_pin),
            "controller_trust": read(args.controller_trust),
        }
        output = assess_attestation(
            load(args.attestation), load(args.security_report),
            inputs, load(args.attestation_trust),
            load(args.independent_attestation_pin),
            load(args.previous_attestation) if args.previous_attestation else None)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            AttributeError, OverflowError, RecursionError, MemoryError) as exc:
        output = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if output["attestation_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
