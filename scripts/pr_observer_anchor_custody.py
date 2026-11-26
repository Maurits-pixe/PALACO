#!/usr/bin/env python3
"""GO-20 v31: offline signed observer-anchor and custody-boundary verifier.

Each supplied v30 view must have a signed observer statement independently
pinned by digest. Observer key custody / organization metadata is supplied by
an external registry, not established by this script. Never grants authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_attestation_multiview import examine_views, SCHEMA as VIEWS_SCHEMA
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape

SCHEMA = "palaco.go20-observer-anchor-bundle.v1"
TRUST_SCHEMA = "palaco.go20-observer-custody-trust.v1"
PIN_SCHEMA = "palaco.go20-observer-anchor-pins.v1"
STATEMENT_SCHEMA = "palaco.go20-observer-anchor-statement.v1"


def verdict(errors: list[str], observed: int = 0, multiview: object = None) -> dict:
    return {
        "schema": "palaco.go20-observer-anchor-verdict.v1",
        "anchors_valid": not errors,
        "observers_verified": observed,
        "multiview_verdict": multiview,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "release_authorized": False, "merge_authorized": False,
        "deployment_authorized": False, "production_commit_performed": False,
    }


def verify_anchors(views: object, history_pins: object, signed_bundle: object,
                   observer_trust: object, independent_heads: object) -> dict:
    try:
        for value in (views, history_pins, signed_bundle, observer_trust, independent_heads):
            validate_shape(value)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        return verdict(["invalid_structure:" + type(exc).__name__])
    if (not isinstance(signed_bundle, dict) or set(signed_bundle) != {"schema", "anchors"} or
            signed_bundle.get("schema") != SCHEMA or
            not isinstance(signed_bundle.get("anchors"), list) or
            not 2 <= len(signed_bundle["anchors"]) <= 8):
        return verdict(["invalid_signed_observer_bundle"])
    if (not isinstance(observer_trust, dict) or set(observer_trust) != {"schema", "observers"} or
            observer_trust.get("schema") != TRUST_SCHEMA or
            not isinstance(observer_trust.get("observers"), dict)):
        return verdict(["invalid_observer_custody_registry"])
    if (not isinstance(independent_heads, dict) or
            set(independent_heads) != {"schema", "heads"} or
            independent_heads.get("schema") != PIN_SCHEMA or
            not isinstance(independent_heads.get("heads"), dict)):
        return verdict(["invalid_independently_retained_receipts"])
    if (not isinstance(views, dict) or views.get("schema") != VIEWS_SCHEMA or
            not isinstance(views.get("views"), list)):
        return verdict(["invalid_views"])
    if not isinstance(history_pins, dict) or not isinstance(history_pins.get("views"), dict):
        return verdict(["invalid_history_pins"])
    view_ids = [v.get("view_id") if isinstance(v, dict) else None
                for v in views["views"]]
    anchor_ids = [a.get("view_id") if isinstance(a, dict) else None
                  for a in signed_bundle["anchors"]]
    if (any(not isinstance(v, str) or not v for v in view_ids + anchor_ids) or
            len(set(view_ids)) != len(view_ids) or
            len(set(anchor_ids)) != len(anchor_ids) or
            set(view_ids) != set(anchor_ids) or
            set(view_ids) != set(observer_trust["observers"]) or
            set(view_ids) != set(independent_heads["heads"]) or
            set(view_ids) != set(history_pins["views"])):
        return verdict(["observer_coverage_or_identity_mismatch"])

    errors: list[str] = []
    orgs: set[str] = set()
    domains: set[str] = set()
    public_keys: set[str] = set()
    verified = 0
    for anchor in signed_bundle["anchors"]:
        vid = anchor["view_id"]
        record = observer_trust["observers"][vid]
        head = independent_heads["heads"][vid]
        if not isinstance(anchor, dict) or set(anchor) != {
            "view_id", "statement", "signature_ed25519_hex"
        } or not isinstance(record, dict) or set(record) != {
            "public_key_hex", "status", "organization_id", "control_domain_id"
        } or not isinstance(head, dict) or set(head) != {
            "minimum_epoch", "receipt_sha256"
        }:
            errors.append(f"invalid_observer_record:{vid}")
            continue
        org, domain, key = (record["organization_id"],
                            record["control_domain_id"], record["public_key_hex"])
        if (not isinstance(org, str) or not org or
                not isinstance(domain, str) or not domain or
                not is_hex(key, 64) or record["status"] != "active"):
            errors.append(f"invalid_or_revoked_observer:{vid}")
            continue
        if org in orgs or domain in domains or key in public_keys:
            errors.append(f"observer_custody_overlap:{vid}")
        orgs.add(org)
        domains.add(domain)
        public_keys.add(key)
        statement = anchor["statement"]
        if (not isinstance(statement, dict) or set(statement) != {
            "schema", "repository", "view_id", "epoch", "history_pin_sha256",
            "organization_id", "control_domain_id", "decision", "authorization"
        } or statement.get("schema") != STATEMENT_SCHEMA):
            errors.append(f"invalid_observer_statement:{vid}")
            continue
        if (type(statement["epoch"]) is not int or
                statement["epoch"] < 0 or
                type(head["minimum_epoch"]) is not int or
                head["minimum_epoch"] < 0 or
                statement["epoch"] < head["minimum_epoch"]):
            errors.append(f"observer_epoch_rollback:{vid}")
        if (statement["repository"] != "Maurits-pixe/PALACO" or
                statement["view_id"] != vid or
                statement["organization_id"] != org or
                statement["control_domain_id"] != domain or
                statement["decision"] != "HOLD" or
                statement["authorization"] != "DENY"):
            errors.append(f"observer_identity_or_authority_mismatch:{vid}")
        if statement["history_pin_sha256"] != canonical_hash(history_pins["views"][vid]):
            errors.append(f"observer_history_pin_mismatch:{vid}")
        if not is_hex(head.get("receipt_sha256"), 64) or (
            canonical_hash(anchor) != head["receipt_sha256"]
        ):
            errors.append(f"independent_observer_head_mismatch:{vid}")
        sig = anchor["signature_ed25519_hex"]
        if not is_hex(sig, 128):
            errors.append(f"invalid_observer_signature_encoding:{vid}")
        else:
            issue = verify_signature(key, sig, statement)
            if issue:
                errors.append(f"observer_signature:{vid}:{issue}")
            else:
                verified += 1

    # Always recalculate v30: signed metadata alone never validates a history.
    try:
        chain = examine_views(views, history_pins)
        if not chain["views_valid"]:
            errors.extend("multiview:" + item for item in chain["errors"])
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, MemoryError) as exc:
        return verdict(errors + ["invalid_multiview:" + type(exc).__name__], verified)
    return verdict(errors, verified, chain)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("views", "history-pins", "signed-anchors",
                 "observer-trust", "independent-heads"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("missing_or_oversize_input")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs)
        result = verify_anchors(
            read(args.views), read(args.history_pins), read(args.signed_anchors),
            read(args.observer_trust), read(args.independent_heads))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError, MemoryError) as exc:
        result = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["anchors_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
