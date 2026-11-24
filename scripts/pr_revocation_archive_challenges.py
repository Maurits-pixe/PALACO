#!/usr/bin/env python3
"""GO-20 v57: independently pinned offline archive retrieval challenges.

Reverify every v56 receipt; require a fresh, epoch-specific Ed25519
challenge response from each independent custodian. Each response binds
a verifier-supplied nonce, the exact checkpoint, claimed retrieval digest,
and a bounded timestamp. Does NOT contact archives, restore data, verify
trusted time, or guarantee challenge one-time use without external state.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_attestation_chain import verify_signature
from pr_revocation_checkpoint_receipts import assess as assess_v56

SCHEMA = "palaco.go20-revocation-archive-challenges.v1"
PIN_SCHEMA = "palaco.go20-revocation-archive-challenges-pin.v1"
RESPONSE_SCHEMA = "palaco.go20-revocation-archive-retrieval-response.v1"


def verdict(errors, epochs=0, responses=0):
    return {
        "schema": "palaco.go20-revocation-archive-challenges-verdict.v1",
        "challenge_evidence_valid": not errors,
        "epochs_verified": epochs,
        "responses_verified": responses,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "remote_availability_verified": False,
        "historical_recovery_performed": False,
        "trusted_time_verified": False,
        "one_time_nonce_enforced": False,
        "missing_history_recovered": False,
        "production_commit_performed": False,
        "merge_authorized": False, "deployment_authorized": False,
    }


def assess(v56_sources, challenges, external_pin, observed_at):
    try:
        for value in (v56_sources, challenges, external_pin):
            validate_shape(value)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if type(observed_at) is not int or observed_at < 0:
        return verdict(["invalid_observation_time"])
    if (not isinstance(v56_sources, dict) or set(v56_sources) != {
            "v55_sources", "custody", "trust", "independent_pin"
    } or not isinstance(challenges, dict) or
            set(challenges) != {"schema", "epochs"} or
            challenges.get("schema") != SCHEMA or
            not isinstance(challenges["epochs"], list) or
            not 2 <= len(challenges["epochs"]) <= 4):
        return verdict(["invalid_challenge_bundle"])
    trust = v56_sources["trust"]
    if (not isinstance(trust, dict) or not isinstance(trust.get("custodians"), dict)):
        return verdict(["invalid_custodian_registry"])
    if (not isinstance(external_pin, dict) or set(external_pin) != {
            "schema", "v56_custody_sha256", "trust_sha256",
            "challenges_sha256", "minimum_epoch", "minimum_responses"
    } or external_pin.get("schema") != PIN_SCHEMA or
            any(not is_hex(external_pin.get(key), 64) for key in (
                "v56_custody_sha256", "trust_sha256", "challenges_sha256")) or
            type(external_pin.get("minimum_epoch")) is not int or
            external_pin["minimum_epoch"] < 1 or
            type(external_pin.get("minimum_responses")) is not int or
            not 2 <= external_pin["minimum_responses"] <= len(trust["custodians"])):
        return verdict(["invalid_external_challenge_pin"])
    if (canonical_hash(v56_sources["custody"]) != external_pin["v56_custody_sha256"] or
            canonical_hash(trust) != external_pin["trust_sha256"] or
            canonical_hash(challenges) != external_pin["challenges_sha256"]):
        return verdict(["independent_challenge_anchor_mismatch"])
    try:
        upstream = assess_v56(*(v56_sources[key] for key in (
            "v55_sources", "custody", "trust", "independent_pin")))
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_v56:" + type(exc).__name__])
    if not upstream["receipt_evidence_valid"]:
        return verdict(["v56:" + e for e in upstream["errors"]])
    archived_epochs = v56_sources["custody"]["epochs"]
    if (len(archived_epochs) != len(challenges["epochs"]) or
            archived_epochs[-1]["epoch"] < external_pin["minimum_epoch"]):
        return verdict(["epoch_rollback_or_incomplete_challenges"])

    errors, counted, responses = [], 0, 0
    nonces = set()
    for i, record in enumerate(challenges["epochs"]):
        archived = archived_epochs[i]
        if (not isinstance(record, dict) or set(record) != {
                "epoch", "nonce_sha256", "issued_at", "expires_at", "responses"
        } or type(record.get("epoch")) is not int or
                record["epoch"] != archived["epoch"] or
                not is_hex(record.get("nonce_sha256"), 64) or
                record["nonce_sha256"] in nonces or
                type(record.get("issued_at")) is not int or
                type(record.get("expires_at")) is not int or
                record["issued_at"] < 0 or
                not record["issued_at"] <= observed_at < record["expires_at"] or
                record["expires_at"] - record["issued_at"] > 3600 or
                not isinstance(record.get("responses"), list) or
                not 2 <= len(record["responses"]) <= 7):
            errors.append(f"invalid_stale_or_reused_challenge:{i}")
            continue
        nonces.add(record["nonce_sha256"])
        allowed = {x["custodian_id"] for x in archived["receipts"]}
        ids, orgs, domains, keys = set(), set(), set(), set()
        valid = 0
        for j, response in enumerate(record["responses"]):
            if (not isinstance(response, dict) or set(response) != {
                    "custodian_id", "checkpoint_sha256", "nonce_sha256",
                    "retrieved_sha256", "signature_ed25519_hex"
            } or not isinstance(response.get("custodian_id"), str) or
                    response["custodian_id"] not in allowed or
                    response["custodian_id"] not in trust["custodians"] or
                    response["custodian_id"] in ids):
                errors.append(f"unrecognized_or_duplicate_response:{i}:{j}")
                continue
            cid = response["custodian_id"]
            ids.add(cid)
            member = trust["custodians"][cid]
            if (not isinstance(member, dict) or set(member) != {
                    "public_key_hex", "organization_id", "domain_id", "status"
            } or member.get("status") != "active" or
                    not is_hex(member.get("public_key_hex"), 64) or
                    not isinstance(member.get("organization_id"), str) or
                    not member["organization_id"] or
                    not isinstance(member.get("domain_id"), str) or
                    not member["domain_id"]):
                errors.append(f"invalid_custodian:{i}:{cid}")
                continue
            org, domain, key = (member["organization_id"], member["domain_id"],
                                member["public_key_hex"])
            if org in orgs or domain in domains or key in keys:
                errors.append(f"overlapping_custody:{i}:{cid}")
                continue
            orgs.add(org)
            domains.add(domain)
            keys.add(key)
            digest = canonical_hash(archived["checkpoint"])
            if (response["checkpoint_sha256"] != digest or
                    response["nonce_sha256"] != record["nonce_sha256"] or
                    response["retrieved_sha256"] != digest):
                errors.append(f"stale_or_corrupt_retrieval_claim:{i}:{cid}")
                continue
            statement = {
                "schema": RESPONSE_SCHEMA,
                "repository": "Maurits-pixe/PALACO",
                "epoch": record["epoch"],
                "nonce_sha256": record["nonce_sha256"],
                "issued_at": record["issued_at"],
                "expires_at": record["expires_at"],
                "checkpoint_sha256": digest,
                "retrieved_sha256": digest,
                "custodian_id": cid,
                "trust_sha256": external_pin["trust_sha256"],
                "v56_custody_sha256": external_pin["v56_custody_sha256"],
                "decision": "HOLD", "authorization": "DENY",
            }
            if (not is_hex(response.get("signature_ed25519_hex"), 128) or
                    verify_signature(key, response["signature_ed25519_hex"],
                                     statement) is not None):
                errors.append(f"invalid_retrieval_signature:{i}:{cid}")
                continue
            valid += 1
        responses += valid
        if valid < external_pin["minimum_responses"]:
            errors.append(f"insufficient_retrieval_response_quorum:{i}")
        else:
            counted += 1
    return verdict(errors, counted, responses)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("v56-evidence", "challenges", "independent-pin"):
        p.add_argument("--" + name, required=True, type=Path)
    p.add_argument("--observed-at", type=int, required=True)
    args = p.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_evidence_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        output = assess(read(args.v56_evidence), read(args.challenges),
                        read(args.independent_pin), args.observed_at)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        output = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["challenge_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
