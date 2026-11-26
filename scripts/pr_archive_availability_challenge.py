#!/usr/bin/env python3
"""GO-20 v48: offline signed archive challenge responses, no network probing.

Requires an independently supplied unpredictable 256-bit challenge nonce and
Ed25519 response from distinct already trusted custodians. A one-time nonce
cannot be enforced offline without externally maintained replay state.
A valid response does not prove live remote availability or actual recovery.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_checkpoint_retention_custody import assess as assess_v47

SCHEMA = "palaco.go20-archive-availability-challenge.v1"
PIN_SCHEMA = "palaco.go20-archive-availability-challenge-pin.v1"
RESPONSE_SCHEMA = "palaco.go20-archive-challenge-response-statement.v1"


def verdict(errors, count=0):
    return {
        "schema": "palaco.go20-archive-availability-challenge-verdict.v1",
        "challenge_evidence_valid": not errors,
        "responses_verified": count,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "remote_availability_verified": False,
        "challenge_freshness_independently_verified": False,
        "restoration_performed": False,
        "missing_witness_quorum_overridden": False,
        "checkpoint_published": False,
        "fence_performed": False, "failover_authorized": False,
        "promotion_performed": False, "release_authorized": False,
        "merge_authorized": False, "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess(chain, chain_pin, witnesses, v45, archive, custodians, retention_pin,
           challenge, responses, independent_pin):
    try:
        for value in (chain, chain_pin, witnesses, v45, archive, custodians,
                      retention_pin, challenge, responses, independent_pin):
            validate_shape(value)
    except (ValueError, TypeError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(challenge, dict) or set(challenge) != {
            "schema", "nonce_sha256", "chain_sha256", "sequence", "minimum_response_count"
    } or challenge.get("schema") != SCHEMA or
            not is_hex(challenge.get("nonce_sha256"), 64) or
            not is_hex(challenge.get("chain_sha256"), 64) or
            type(challenge.get("sequence")) is not int or challenge["sequence"] < 0 or
            type(challenge.get("minimum_response_count")) is not int or
            challenge["minimum_response_count"] < 2):
        return verdict(["invalid_challenge"])
    if (not isinstance(independent_pin, dict) or set(independent_pin) != {
            "schema", "challenge_sha256", "trusted_chain_sha256",
            "minimum_sequence", "minimum_responses"
    } or independent_pin.get("schema") != PIN_SCHEMA or
            not is_hex(independent_pin.get("challenge_sha256"), 64) or
            not is_hex(independent_pin.get("trusted_chain_sha256"), 64) or
            type(independent_pin.get("minimum_sequence")) is not int or
            independent_pin["minimum_sequence"] < 0 or
            type(independent_pin.get("minimum_responses")) is not int or
            independent_pin["minimum_responses"] < 2):
        return verdict(["invalid_challenge_pin"])
    if (not isinstance(responses, dict) or set(responses) != {"schema", "entries"} or
            responses.get("schema") != "palaco.go20-archive-availability-responses.v1" or
            not isinstance(responses.get("entries"), list) or
            not 2 <= len(responses["entries"]) <= 5):
        return verdict(["invalid_responses"])
    if (canonical_hash(challenge) != independent_pin["challenge_sha256"] or
            challenge["chain_sha256"] != independent_pin["trusted_chain_sha256"] or
            challenge["chain_sha256"] != canonical_hash(chain)):
        return verdict(["challenge_anchor_mismatch"])
    if (challenge["sequence"] < independent_pin["minimum_sequence"] or
            not isinstance(chain_pin, dict) or
            challenge["sequence"] != chain_pin.get("last_sequence")):
        return verdict(["stale_or_unpinned_sequence"])
    if (not isinstance(custodians, dict) or
            not isinstance(custodians.get("members"), dict)):
        return verdict(["invalid_custodian_register"])
    minimum = max(challenge["minimum_response_count"],
                  independent_pin["minimum_responses"])
    if minimum > len(custodians["members"]):
        return verdict(["unachievable_response_quorum"])
    baseline = assess_v47(chain, chain_pin, witnesses, v45,
                          archive, custodians, retention_pin)
    if not baseline["custody_evidence_valid"]:
        return verdict(["v47:" + error for error in baseline["errors"]])

    errors, valid = [], 0
    used_id, used_org, used_domain, used_key = set(), set(), set(), set()
    archived_ids = {copy["custodian_id"] for copy in archive["copies"]}
    for index, response in enumerate(responses["entries"]):
        if (not isinstance(response, dict) or set(response) != {
                "custodian_id", "nonce_sha256", "chain_sha256",
                "sequence", "signature_ed25519_hex"
        } or not isinstance(response.get("custodian_id"), str) or
                response["custodian_id"] in used_id or
                response["custodian_id"] not in custodians["members"] or
                response["custodian_id"] not in archived_ids):
            errors.append(f"unknown_duplicate_or_unarchived_custodian:{index}")
            continue
        mid = response["custodian_id"]
        used_id.add(mid)
        record = custodians["members"][mid]
        if (response.get("nonce_sha256") != challenge["nonce_sha256"] or
                response.get("chain_sha256") != challenge["chain_sha256"] or
                type(response.get("sequence")) is not int or
                response["sequence"] != challenge["sequence"]):
            errors.append(f"stale_or_mismatched_response:{index}")
            continue
        org, domain, key = (record["organization_id"], record["domain_id"],
                            record["public_key_hex"])
        if (org in used_org or domain in used_domain or key in used_key or
                record["status"] != "active"):
            errors.append(f"invalid_response_custody:{index}")
            continue
        used_org.add(org)
        used_domain.add(domain)
        used_key.add(key)
        statement = {
            "schema": RESPONSE_SCHEMA,
            "repository": "Maurits-pixe/PALACO",
            "custodian_id": mid,
            "nonce_sha256": challenge["nonce_sha256"],
            "chain_sha256": challenge["chain_sha256"],
            "sequence": challenge["sequence"],
            "trust_sha256": canonical_hash(custodians),
            "decision": "HOLD",
            "authorization": "DENY",
        }
        if (not is_hex(response.get("signature_ed25519_hex"), 128) or
                verify_signature(key, response["signature_ed25519_hex"], statement)
                is not None):
            errors.append(f"invalid_challenge_signature:{index}")
            continue
        valid += 1
    if valid < minimum:
        errors.append("challenge_response_quorum_not_met")
    return verdict(errors, valid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("chain", "chain-pin", "witnesses", "v45", "archive", "custodians",
             "retention-pin", "challenge", "responses", "independent-pin")
    for name in names:
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = assess(*(read(getattr(args, name.replace("-", "_"))) for name in names))
    except (OSError, TypeError, ValueError, UnicodeError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["challenge_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
