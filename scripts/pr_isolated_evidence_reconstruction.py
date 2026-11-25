#!/usr/bin/env python3
"""GO-20 v58: isolated, read-only reconstruction of archive evidence copies.

Reverify complete v57 chain; reconstruct historical checkpoints exclusively
in memory from externally supplied JSON copies. Compare full canonical data
against the original pinned epochs. Independent Ed25519 reviewers sign the
exact comparison report and input bundle. No file/database writes, network,
production restoration, or proof that claimed copies came from remote media.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_attestation_chain import verify_signature
from pr_governance_hardening import validate_shape
from pr_revocation_archive_challenges import assess as assess_v57

SCHEMA = "palaco.go20-isolated-reconstruction-evidence.v1"
PIN_SCHEMA = "palaco.go20-isolated-reconstruction-pin.v1"
REVIEW_SCHEMA = "palaco.go20-isolated-reconstruction-reviewers.v1"
REPORT_SCHEMA = "palaco.go20-isolated-reconstruction-report.v1"


def verdict(errors, epochs=0, copies=0, reviewers=0):
    return {
        "schema": "palaco.go20-isolated-reconstruction-verdict.v1",
        "isolated_evidence_valid": not errors,
        "epochs_compared": epochs,
        "copies_compared": copies,
        "reviewer_signatures_verified": reviewers,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "remote_media_read_performed": False,
        "live_availability_verified": False,
        "production_restoration_performed": False,
        "independent_media_custody_verified": False,
        "challenge_reopened": False, "failover_authorized": False,
        "merge_authorized": False, "deployment_authorized": False,
        "production_commit_performed": False,
    }


def assess(v57, reconstruction, reviewers, pin, observed_at):
    try:
        for item in (v57, reconstruction, reviewers, pin):
            validate_shape(item)
    except (TypeError, ValueError, OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if type(observed_at) is not int or observed_at < 0:
        return verdict(["invalid_observation_time"])
    if (not isinstance(v57, dict) or set(v57) != {
                "v56_sources", "challenges", "independent_pin"
            } or not isinstance(reconstruction, dict) or
            set(reconstruction) != {"schema", "epochs", "review_signatures"} or
            reconstruction.get("schema") != SCHEMA or
            not isinstance(reconstruction.get("epochs"), list) or
            not 2 <= len(reconstruction["epochs"]) <= 4 or
            not isinstance(reconstruction.get("review_signatures"), list) or
            not 2 <= len(reconstruction["review_signatures"]) <= 5):
        return verdict(["invalid_reconstruction_bundle"])
    if (not isinstance(reviewers, dict) or set(reviewers) != {"schema", "members"} or
            reviewers.get("schema") != REVIEW_SCHEMA or
            not isinstance(reviewers.get("members"), dict) or
            not 2 <= len(reviewers["members"]) <= 5):
        return verdict(["invalid_reviewer_trust"])
    if (not isinstance(pin, dict) or set(pin) != {
            "schema", "v57_sha256", "copies_sha256", "reviewer_trust_sha256",
            "minimum_epoch", "minimum_copies", "minimum_reviews"
    } or pin.get("schema") != PIN_SCHEMA or
            any(not is_hex(pin.get(name), 64) for name in (
                "v57_sha256", "copies_sha256", "reviewer_trust_sha256")) or
            type(pin.get("minimum_epoch")) is not int or
            pin["minimum_epoch"] < 1 or
            type(pin.get("minimum_copies")) is not int or
            not 2 <= pin["minimum_copies"] <= 5 or
            type(pin.get("minimum_reviews")) is not int or
            not 2 <= pin["minimum_reviews"] <= len(reviewers["members"])):
        return verdict(["invalid_independent_reconstruction_pin"])
    # Hash only the immutable copies; reviewer signatures cannot re-pin data.
    copies = {"schema": SCHEMA, "epochs": reconstruction["epochs"]}
    if (canonical_hash(v57) != pin["v57_sha256"] or
            canonical_hash(copies) != pin["copies_sha256"] or
            canonical_hash(reviewers) != pin["reviewer_trust_sha256"]):
        return verdict(["independent_reconstruction_anchor_mismatch"])
    try:
        underlying = assess_v57(
            v57["v56_sources"], v57["challenges"],
            v57["independent_pin"], observed_at)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(["malformed_v57:" + type(exc).__name__])
    if not underlying["challenge_evidence_valid"]:
        return verdict(["v57:" + err for err in underlying["errors"]])
    original = v57["v56_sources"]["custody"]["epochs"]
    claimed = v57["challenges"]["epochs"]
    if (len(original) != len(reconstruction["epochs"]) or
            original[-1]["epoch"] < pin["minimum_epoch"]):
        return verdict(["incomplete_or_rollback_reconstruction"])
    errors, epochs, copies_checked = [], 0, 0
    for index, item in enumerate(reconstruction["epochs"]):
        expected = original[index]["checkpoint"]
        challenge = claimed[index]
        if (not isinstance(item, dict) or set(item) != {
                "epoch", "nonce_sha256", "copies"
            } or type(item.get("epoch")) is not int or
                item["epoch"] != original[index]["epoch"] or
                item.get("nonce_sha256") != challenge["nonce_sha256"] or
                not isinstance(item.get("copies"), list) or
                not pin["minimum_copies"] <= len(item["copies"]) <= 5):
            errors.append(f"missing_or_invalid_epoch_copy:{index}")
            continue
        approved = {r["custodian_id"] for r in challenge["responses"]}
        used, orgs, domains, keys = set(), set(), set(), set()
        accepted = 0
        for j, copy in enumerate(item["copies"]):
            if (not isinstance(copy, dict) or set(copy) != {
                    "custodian_id", "checkpoint"
                } or not isinstance(copy.get("custodian_id"), str) or
                    copy["custodian_id"] in used or
                    copy["custodian_id"] not in approved):
                errors.append(f"unknown_or_duplicate_restoration_copy:{index}:{j}")
                continue
            mid = copy["custodian_id"]
            used.add(mid)
            record = v57["v56_sources"]["trust"]["custodians"][mid]
            org, domain, key = (record["organization_id"], record["domain_id"],
                                record["public_key_hex"])
            if org in orgs or domain in domains or key in keys:
                errors.append(f"overlapping_restoration_sources:{index}:{mid}")
                continue
            orgs.add(org)
            domains.add(domain)
            keys.add(key)
            if (not isinstance(copy.get("checkpoint"), dict) or
                    copy["checkpoint"] != expected or
                    canonical_hash(copy["checkpoint"]) != canonical_hash(expected)):
                errors.append(f"restored_content_mismatch:{index}:{mid}")
                continue
            accepted += 1
        copies_checked += accepted
        if accepted < pin["minimum_copies"]:
            errors.append(f"restoration_copy_quorum_not_met:{index}")
        else:
            epochs += 1
    if errors:
        return verdict(errors, epochs, copies_checked)

    statement = {
        "schema": REPORT_SCHEMA,
        "repository": "Maurits-pixe/PALACO",
        "v57_sha256": pin["v57_sha256"],
        "copies_sha256": pin["copies_sha256"],
        "reviewer_trust_sha256": pin["reviewer_trust_sha256"],
        "epoch_count": epochs,
        "copy_count": copies_checked,
        "decision": "HOLD", "authorization": "DENY",
    }
    verified, ids, orgs, domains, keys = 0, set(), set(), set(), set()
    for j, signature in enumerate(reconstruction["review_signatures"]):
        if (not isinstance(signature, dict) or set(signature) != {
                "reviewer_id", "signature_ed25519_hex"
            } or not isinstance(signature.get("reviewer_id"), str) or
                signature["reviewer_id"] in ids or
                signature["reviewer_id"] not in reviewers["members"]):
            errors.append(f"unknown_or_duplicate_reviewer:{j}")
            continue
        rid = signature["reviewer_id"]
        ids.add(rid)
        member = reviewers["members"][rid]
        if (not isinstance(member, dict) or set(member) != {
                "public_key_hex", "organization_id", "domain_id", "status"
            } or not is_hex(member.get("public_key_hex"), 64) or
                member.get("status") != "active" or
                not isinstance(member.get("organization_id"), str) or
                not member["organization_id"] or
                not isinstance(member.get("domain_id"), str) or
                not member["domain_id"]):
            errors.append(f"invalid_reviewer:{j}:{rid}")
            continue
        org, domain, key = (member["organization_id"], member["domain_id"],
                            member["public_key_hex"])
        if org in orgs or domain in domains or key in keys:
            errors.append(f"overlapping_reviewer_custody:{j}:{rid}")
            continue
        orgs.add(org)
        domains.add(domain)
        keys.add(key)
        full_statement = {**statement, "reviewer_id": rid}
        if (not is_hex(signature.get("signature_ed25519_hex"), 128) or
                verify_signature(key, signature["signature_ed25519_hex"],
                                 full_statement) is not None):
            errors.append(f"invalid_review_signature:{j}:{rid}")
            continue
        verified += 1
    if verified < pin["minimum_reviews"]:
        errors.append("independent_review_quorum_missing")
    return verdict(errors, epochs, copies_checked, verified)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("v57-evidence", "reconstruction", "reviewer-trust", "independent-pin"):
        p.add_argument("--" + name, required=True, type=Path)
    p.add_argument("--observed-at", required=True, type=int)
    args = p.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("invalid_input")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        out = assess(read(args.v57_evidence), read(args.reconstruction),
                     read(args.reviewer_trust), read(args.independent_pin),
                     args.observed_at)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError,
            OverflowError, RecursionError, MemoryError) as exc:
        out = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["isolated_evidence_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
