#!/usr/bin/env python3
"""Read-only PALACO trust-registry and replay gate for signed report chains.

All registries and replay journals MUST be independently provisioned. A
successful result is advisory and never changes GO-13 HOLD / DENY.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from pr_attestation_chain import assess_chain, digest, is_hex, unique_pairs

SCHEMA = "palaco.pr-trust-registry.v1"
JOURNAL_SCHEMA = "palaco.pr-replay-journal.v1"


def assess_policy(chain: object, registry: object, replay_journal: object) -> dict:
    issues: list[str] = []
    trusted: dict[str, str] = {}
    if not isinstance(registry, dict) or set(registry) != {"schema", "keys"} or registry.get("schema") != SCHEMA:
        issues.append("invalid_trust_registry")
        keys = {}
    else:
        keys = registry.get("keys")
        if not isinstance(keys, dict) or not keys:
            issues.append("invalid_trust_registry")
            keys = {}
    for key_id, record in keys.items():
        if not isinstance(key_id, str) or not key_id or not isinstance(record, dict) or set(record) != {
            "public_key_hex", "status", "valid_from_sequence", "valid_until_sequence"
        }:
            issues.append("invalid_key_record")
            continue
        first, last = record["valid_from_sequence"], record["valid_until_sequence"]
        if (not is_hex(record["public_key_hex"], 64) or record["status"] not in
                ("active", "revoked") or type(first) is not int or first < 0 or
                (last is not None and (type(last) is not int or last < first))):
            issues.append("invalid_key_record")
            continue
        trusted[key_id] = record["public_key_hex"]

    if not isinstance(replay_journal, dict) or set(replay_journal) != {"schema", "consumed_entry_sha256"} or replay_journal.get("schema") != JOURNAL_SCHEMA:
        issues.append("invalid_replay_journal")
        consumed = []
    else:
        consumed = replay_journal.get("consumed_entry_sha256")
        if not isinstance(consumed, list) or len(consumed) > 10000 or any(not is_hex(h, 64) for h in consumed) or len(set(consumed)) != len(consumed):
            issues.append("invalid_replay_journal")
            consumed = []
    if not issues:
        consumed_set = set(consumed)
        seen = set()
        entries = chain.get("entries", []) if isinstance(chain, dict) else []
        if isinstance(entries, list):
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                key_id = entry.get("key_id")
                if not isinstance(key_id, str) or key_id not in keys:
                    issues.append(f"unregistered_signer:{i}")
                else:
                    record = keys[key_id]
                    if record["status"] == "revoked":
                        issues.append(f"revoked_signer:{i}")
                    if i < record["valid_from_sequence"] or (
                        record["valid_until_sequence"] is not None and i > record["valid_until_sequence"]
                    ):
                        issues.append(f"signer_outside_sequence_scope:{i}")
                entry_sha = entry.get("entry_sha256")
                if is_hex(entry_sha, 64):
                    if entry_sha in consumed_set:
                        issues.append(f"replayed_entry:{i}")
                    if entry_sha in seen:
                        issues.append(f"duplicate_chain_entry:{i}")
                    seen.add(entry_sha)

    # Baseline Ed25519 and report-chain checks are always mandatory.
    baseline = assess_chain(chain, trusted)
    issues.extend(baseline["errors"])
    return {
        "schema": "palaco.pr-trust-verdict.v1",
        "policy_valid": not issues and baseline["chain_valid"],
        "issues": sorted(set(issues)),
        "checked_head_entry_sha256": baseline["head_entry_sha256"] if not issues else None,
        "decision": "HOLD",
        "authorization": "DENY",
        "note": "Read-only advisory. Journal freshness, trust-store provenance, and human authorization are external.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--replay-journal", type=Path, required=True)
    args = parser.parse_args()
    try:
        chain = json.loads(args.chain.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        registry = json.loads(args.registry.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        journal = json.loads(args.replay_journal.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        verdict = assess_policy(chain, registry, journal)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        verdict = {
            "schema": "palaco.pr-trust-verdict.v1",
            "policy_valid": False, "issues": ["invalid_input:" + type(exc).__name__],
            "checked_head_entry_sha256": None, "decision": "HOLD", "authorization": "DENY",
        }
    print(json.dumps(verdict, sort_keys=True, indent=2))
    return 0 if verdict["policy_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
