#!/usr/bin/env python3
"""Offline signed state snapshot validation and compare-and-swap replay proposal.

No state mutations: proposal is NOT a receipt or authorization. Root public key
must come from outside the attestation chain and any submitted state bundle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from pr_attestation_chain import digest, is_hex, unique_pairs, verify_signature
from pr_attestation_policy import assess_policy

SCHEMA = "palaco.pr-signed-state.v1"
PROPOSAL_SCHEMA = "palaco.pr-replay-proposal.v1"


def validate_snapshot(envelope: object, root_public_hex: object, expected_revision: object) -> list[str]:
    errors = []
    if not is_hex(root_public_hex, 64):
        errors.append("invalid_pinned_root")
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature_ed25519_hex"}:
        return errors + ["invalid_snapshot_envelope"]
    payload = envelope["payload"]
    if not isinstance(payload, dict) or set(payload) != {"schema", "revision", "registry", "journal"}:
        return errors + ["invalid_snapshot_payload"]
    revision = payload.get("revision")
    if payload.get("schema") != SCHEMA or type(revision) is not int or revision < 0:
        errors.append("invalid_revision")
    if type(expected_revision) is not int or revision != expected_revision:
        errors.append("revision_mismatch")
    signature = envelope["signature_ed25519_hex"]
    if not is_hex(signature, 128):
        errors.append("invalid_snapshot_signature")
    elif is_hex(root_public_hex, 64):
        # Domain-separated signed statement; payload includes BOTH registry and journal.
        statement = {"schema": "palaco.pr-state-signature.v1", "payload_sha256": digest(payload)}
        issue = verify_signature(root_public_hex, signature, statement)
        if issue:
            errors.append(issue)
    return sorted(set(errors))


def plan_replay(chain: object, envelope: object, root_public_hex: object, expected_revision: object) -> dict:
    errors = validate_snapshot(envelope, root_public_hex, expected_revision)
    verdict = None
    proposal = None
    if not errors:
        state = envelope["payload"]
        verdict = assess_policy(chain, state["registry"], state["journal"])
        errors.extend(verdict["issues"])
        if verdict["policy_valid"]:
            entries = chain["entries"]
            consumed = state["journal"]["consumed_entry_sha256"]
            new_hashes = [entry["entry_sha256"] for entry in entries]
            if any(not is_hex(v, 64) for v in new_hashes):
                errors.append("invalid_proposed_hash")
            else:
                next_journal = {
                    "schema": "palaco.pr-replay-journal.v1",
                    "consumed_entry_sha256": sorted(consumed + new_hashes),
                }
                if len(next_journal["consumed_entry_sha256"]) > 10000:
                    errors.append("journal_capacity_exceeded")
                else:
                    proposal = {
                        "schema": PROPOSAL_SCHEMA,
                        "expected_revision": expected_revision,
                        "expected_state_sha256": digest(state),
                        "new_journal_sha256": digest(next_journal),
                        "new_journal": next_journal,
                        "entry_hashes": new_hashes,
                        "atomic_commit_performed": False,
                    }
                    proposal["proposal_sha256"] = digest(proposal)
    if errors:
        proposal = None
    return {
        "schema": "palaco.pr-replay-preflight.v1",
        "verified_snapshot": not validate_snapshot(envelope, root_public_hex, expected_revision),
        "technical_preflight_valid": not errors and proposal is not None,
        "errors": sorted(set(errors)),
        "proposal": proposal,
        "decision": "HOLD",
        "authorization": "DENY",
        "note": "Read-only proposal. No atomic consume, freshness guarantee or release approval.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain", type=Path)
    parser.add_argument("--signed-state", type=Path, required=True)
    parser.add_argument("--root-public-key", required=True, help="Pinned independent 32-byte Ed25519 public key as hex")
    parser.add_argument("--expected-revision", type=int, required=True)
    args = parser.parse_args()
    try:
        chain = json.loads(args.chain.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        envelope = json.loads(args.signed_state.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        result = plan_replay(chain, envelope, args.root_public_key, args.expected_revision)
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        result = {
            "schema": "palaco.pr-replay-preflight.v1",
            "verified_snapshot": False, "technical_preflight_valid": False,
            "errors": ["invalid_input:" + type(exc).__name__], "proposal": None,
            "decision": "HOLD", "authorization": "DENY",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["technical_preflight_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
