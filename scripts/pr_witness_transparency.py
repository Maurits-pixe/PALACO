#!/usr/bin/env python3
"""GO-20 v20: offline, anchored witness transparency journal reconciliation.

A supplied, signed journal plus an independently pinned head is required
for each witness. This is a read-only proof checker, NOT a publisher, time
oracle, replicated store, or release authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_audit_integrity import ZERO, canonical_hash, is_hex, unique_pairs
from pr_audit_witness_forks import TRUST_SCHEMA

SCHEMA = "palaco.go20-witness-transparency.v1"
PIN_SCHEMA = "palaco.go20-transparency-pins.v1"
ENTRY_SCHEMA = "palaco.go20-transparency-entry.v1"
MAX_LOGS = 16
MAX_ENTRIES = 256


def verdict(errors: list[str], conflicting: dict[int, set[str]] | None = None,
            verified_entries: int = 0) -> dict:
    forks = conflicting or {}
    return {
        "schema": "palaco.go20-transparency-verdict.v1",
        "history_valid": not errors,
        "fork_detected": bool(forks),
        "fork_revisions": sorted(forks),
        "conflicting_checkpoint_sha256": {
            str(revision): sorted(forks[revision]) for revision in sorted(forks)
        },
        "verified_entry_count": verified_entries,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
    }


def verify_transparency(logbook: object, witness_trust: object,
                        pinned_heads: object, start_revision: object) -> dict:
    errors: list[str] = []
    if type(start_revision) is not int or start_revision < 0:
        errors.append("invalid_start_revision")
    if (not isinstance(logbook, dict) or set(logbook) != {"schema", "logs"} or
            logbook.get("schema") != SCHEMA or not isinstance(logbook.get("logs"), list) or
            not 2 <= len(logbook["logs"]) <= MAX_LOGS):
        return verdict(errors + ["invalid_logbook"])
    if (not isinstance(witness_trust, dict) or set(witness_trust) != {"schema", "keys"} or
            witness_trust.get("schema") != TRUST_SCHEMA or
            not isinstance(witness_trust.get("keys"), dict)):
        return verdict(errors + ["invalid_witness_trust"])
    if (not isinstance(pinned_heads, dict) or set(pinned_heads) != {"schema", "witnesses"} or
            pinned_heads.get("schema") != PIN_SCHEMA or
            not isinstance(pinned_heads.get("witnesses"), dict)):
        return verdict(errors + ["invalid_independent_pins"])
    keys = witness_trust["keys"]
    pins = pinned_heads["witnesses"]
    logs = logbook["logs"]
    identities = [log.get("witness_id") if isinstance(log, dict) else None for log in logs]
    if (any(not isinstance(wid, str) or not wid for wid in identities) or
            len(set(identities)) != len(identities)):
        return verdict(errors + ["duplicate_or_invalid_witness_log"])
    if set(identities) != set(pins):
        errors.append("independent_pin_coverage_mismatch")
    for identity in identities:
        record = keys.get(identity)
        if (not isinstance(record, dict) or set(record) != {"public_key_hex", "status"} or
                not is_hex(record.get("public_key_hex"), 64) or
                record.get("status") != "active"):
            errors.append(f"untrusted_or_revoked_witness:{identity}")
    if errors:
        return verdict(errors)

    published: dict[int, set[str]] = {}
    counts: dict[int, set[str]] = {}
    verified = 0
    for log in logs:
        wid = log["witness_id"]
        if set(log) != {"witness_id", "entries"}:
            errors.append(f"invalid_log:{wid}")
            continue
        entries = log["entries"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
            errors.append(f"invalid_entry_count:{wid}")
            continue
        pin = pins[wid]
        if (not isinstance(pin, dict) or set(pin) != {"last_sequence", "head_sha256"} or
                type(pin.get("last_sequence")) is not int or
                not is_hex(pin.get("head_sha256"), 64)):
            errors.append(f"invalid_independent_pin:{wid}")
            continue
        previous = ZERO
        for pos, entry in enumerate(entries, 1):
            if not isinstance(entry, dict) or set(entry) != {
                "sequence", "revision", "checkpoint_payload_sha256",
                "previous_entry_sha256", "entry_sha256", "signature_ed25519_hex"
            }:
                errors.append(f"invalid_entry:{wid}:{pos}")
                continue
            if type(entry["sequence"]) is not int or entry["sequence"] != pos:
                errors.append(f"sequence_gap:{wid}:{pos}")
            if type(entry["revision"]) is not int or entry["revision"] != start_revision + pos - 1:
                errors.append(f"revision_gap:{wid}:{pos}")
            if entry["previous_entry_sha256"] != previous:
                errors.append(f"broken_history:{wid}:{pos}")
            if not is_hex(entry["checkpoint_payload_sha256"], 64):
                errors.append(f"invalid_checkpoint_digest:{wid}:{pos}")
            statement = {
                "schema": ENTRY_SCHEMA, "witness_id": wid,
                "sequence": entry["sequence"], "revision": entry["revision"],
                "checkpoint_payload_sha256": entry["checkpoint_payload_sha256"],
                "previous_entry_sha256": entry["previous_entry_sha256"],
            }
            calculated = canonical_hash(statement)
            if entry["entry_sha256"] != calculated:
                errors.append(f"entry_hash_mismatch:{wid}:{pos}")
            if not is_hex(entry["signature_ed25519_hex"], 128):
                errors.append(f"invalid_signature_encoding:{wid}:{pos}")
            else:
                issue = verify_signature(keys[wid]["public_key_hex"],
                                         entry["signature_ed25519_hex"], statement)
                if issue:
                    errors.append(f"signature:{wid}:{pos}:{issue}")
            previous = calculated
            if type(entry["revision"]) is int and is_hex(entry["checkpoint_payload_sha256"], 64):
                published.setdefault(entry["revision"], set()).add(entry["checkpoint_payload_sha256"])
                counts.setdefault(entry["revision"], set()).add(wid)
            verified += 1
        if pin["last_sequence"] != len(entries) or pin["head_sha256"] != previous:
            errors.append(f"independent_head_mismatch:{wid}")

    if not errors:
        # Only compare complete, cryptographically authenticated histories.
        for revision, group in counts.items():
            if len(group) != len(identities):
                errors.append(f"publication_coverage_gap:{revision}")
        if len({len(log["entries"]) for log in logs}) != 1:
            errors.append("unequal_publication_horizons")
    if errors:
        return verdict(errors, verified_entries=verified)
    forks = {revision: hashes for revision, hashes in published.items() if len(hashes) > 1}
    if forks:
        errors.append("conflicting_signed_publications")
    return verdict(errors, conflicting=forks, verified_entries=verified)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logbook", type=Path, required=True)
    parser.add_argument("--witness-trust", type=Path, required=True)
    parser.add_argument("--independent-pins", type=Path, required=True)
    parser.add_argument("--start-revision", type=int, required=True)
    args = parser.parse_args()
    try:
        def read(path: Path):
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        output = verify_transparency(read(args.logbook), read(args.witness_trust),
                                     read(args.independent_pins), args.start_revision)
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        output = verdict(["invalid_input:" + type(exc).__name__])
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["history_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
