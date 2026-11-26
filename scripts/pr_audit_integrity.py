#!/usr/bin/env python3
"""GO-20 v15 offline audit export integrity verifier.

The expected anchor MUST be provided independently of the untrusted export.
Hashes alone neither authenticate a producer nor make records immutable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "palaco.go20-audit-export.v1"
MAX_ENTRIES = 10000
ZERO = "0" * 64


def canonical_hash(value: object) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(
        ch in "0123456789abcdef" for ch in value
    )


def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def verify_export(payload: object, external_anchor: object) -> dict:
    errors: list[str] = []
    head = ZERO
    if not is_hex(external_anchor, 64):
        errors.append("invalid_external_anchor")
    if not isinstance(payload, dict) or set(payload) != {"schema", "events"} or payload.get("schema") != SCHEMA:
        errors.append("invalid_export_schema")
        entries = []
    else:
        entries = payload["events"]
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            errors.append("invalid_export_length")
            entries = []

    for index, event in enumerate(entries):
        if not isinstance(event, dict) or set(event) != {
            "id", "operation", "actor_role", "tenant_role", "entry_sha256",
            "previous_sha256", "event_sha256"
        }:
            errors.append(f"invalid_event:{index}")
            continue
        if type(event["id"]) is not int or event["id"] != index + 1:
            errors.append(f"event_sequence_mismatch:{index}")
        if event["operation"] not in ("INSERT", "UPDATE", "DELETE"):
            errors.append(f"invalid_operation:{index}")
        if (not isinstance(event["actor_role"], str) or not event["actor_role"] or
                not isinstance(event["tenant_role"], str) or not event["tenant_role"]):
            errors.append(f"invalid_identity:{index}")
        if not is_hex(event["entry_sha256"], 64):
            errors.append(f"invalid_entry_digest:{index}")
        if event["previous_sha256"] != head:
            errors.append(f"broken_chain:{index}")
        try:
            calculated = canonical_hash({k: v for k, v in event.items() if k != "event_sha256"})
        except (TypeError, ValueError, OverflowError, RecursionError):
            calculated = None
        if not is_hex(event["event_sha256"], 64) or calculated != event["event_sha256"]:
            errors.append(f"event_digest_mismatch:{index}")
        head = event["event_sha256"] if is_hex(event["event_sha256"], 64) else ZERO
    if is_hex(external_anchor, 64) and head != external_anchor:
        errors.append("external_anchor_mismatch")
    return {
        "schema": "palaco.go20-audit-verdict.v1",
        "integrity_valid": not errors,
        "errors": sorted(set(errors)),
        "observed_head_sha256": head,
        "decision": "HOLD",
        "authorization": "DENY",
        "note": "Offline structural verification; external anchor authenticity and freshness are separate.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--expected-head-sha256", required=True,
                        help="Independent expected digest, not read from the export")
    args = parser.parse_args()
    try:
        data = json.loads(args.export.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        result = verify_export(data, args.expected_head_sha256)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        result = {
            "schema": "palaco.go20-audit-verdict.v1",
            "integrity_valid": False, "errors": ["unreadable_export:" + type(exc).__name__],
            "observed_head_sha256": None, "decision": "HOLD", "authorization": "DENY",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["integrity_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
