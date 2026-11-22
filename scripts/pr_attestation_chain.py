#!/usr/bin/env python3
"""Offline PALACO report-chain and Ed25519 attestation verification.

Advisory only. Trusted public keys must be supplied separately from the chain.
Never grants release authorization or changes the state of a PR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ZERO = "0" * 64
SCHEMA = "palaco.pr-attestation-chain.v1"
MAX_ENTRIES = 256


def digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(
        char in "0123456789abcdef" for char in value
    )


def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def verify_signature(public_key_hex: str, signature_hex: str, statement: dict) -> str | None:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return "crypto_backend_unavailable"
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, bytes.fromhex(digest(statement)))
    except (ValueError, TypeError):
        return "invalid_public_key_or_signature"
    except Exception as exc:
        # Fail closed; no trust inferred from a backend exception.
        return "signature_invalid"
    return None


def assess_chain(chain: object, trusted_keys: object) -> dict:
    errors = []
    if not isinstance(trusted_keys, dict) or not trusted_keys or any(
        not isinstance(key_id, str) or not key_id or not is_hex(key, 64)
        for key_id, key in trusted_keys.items()
    ):
        errors.append("invalid_external_trust_store")
    if not isinstance(chain, dict) or set(chain) != {"schema", "entries"}:
        errors.append("invalid_chain")
        entries = []
    else:
        if chain["schema"] != SCHEMA:
            errors.append("unsupported_chain_schema")
        entries = chain["entries"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
            errors.append("invalid_chain_length")
            entries = []
    previous = ZERO
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
            "sequence", "previous_entry_sha256", "report", "key_id",
            "signature_ed25519_hex", "entry_sha256"
        }:
            errors.append(f"invalid_entry:{index}")
            continue
        if type(entry["sequence"]) is not int or entry["sequence"] != index:
            errors.append(f"sequence_mismatch:{index}")
        if entry["previous_entry_sha256"] != previous:
            errors.append(f"chain_link_mismatch:{index}")
        report = entry["report"]
        if not isinstance(report, dict) or report.get("decision") != "HOLD" or report.get("authorization") != "DENY":
            errors.append(f"unauthorized_report_state:{index}")
        else:
            report_hash = report.get("report_sha256")
            raw = {k: v for k, v in report.items() if k != "report_sha256"}
            try:
                valid = is_hex(report_hash, 64) and digest(raw) == report_hash
            except (TypeError, ValueError, OverflowError, RecursionError):
                valid = False
            if not valid:
                errors.append(f"report_digest_mismatch:{index}")
        statement = {
            "schema": "palaco.pr-attestation-statement.v1",
            "sequence": index,
            "previous_entry_sha256": entry["previous_entry_sha256"],
            "report_sha256": report.get("report_sha256") if isinstance(report, dict) else None,
        }
        key_id = entry["key_id"]
        signature = entry["signature_ed25519_hex"]
        if not isinstance(key_id, str) or not isinstance(trusted_keys, dict) or key_id not in trusted_keys:
            errors.append(f"unknown_signer:{index}")
        elif not is_hex(signature, 128):
            errors.append(f"invalid_signature_encoding:{index}")
        elif is_hex(trusted_keys[key_id], 64):
            issue = verify_signature(trusted_keys[key_id], signature, statement)
            if issue:
                errors.append(f"{issue}:{index}")
        else:
            errors.append(f"invalid_trusted_key:{index}")
        try:
            entry_payload = {k: v for k, v in entry.items() if k != "entry_sha256"}
            calculated = digest(entry_payload)
        except (TypeError, ValueError, OverflowError, RecursionError):
            calculated = None
        if calculated is None or entry["entry_sha256"] != calculated:
            errors.append(f"entry_digest_mismatch:{index}")
        previous = calculated if calculated is not None else ZERO
    return {
        "schema": "palaco.pr-attestation-verdict.v1",
        "chain_valid": not errors,
        "errors": sorted(set(errors)),
        "head_entry_sha256": previous if entries and not errors else None,
        "decision": "HOLD",
        "authorization": "DENY",
        "note": "Verified signatures do not confer reviewer or release authority.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chain", type=Path)
    parser.add_argument("--trust-store", type=Path, required=True,
                        help="Independent local key-id to Ed25519 public-key hex mapping")
    args = parser.parse_args()
    try:
        chain = json.loads(args.chain.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        trusted = json.loads(args.trust_store.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        result = assess_chain(chain, trusted)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        result = {
            "schema": "palaco.pr-attestation-verdict.v1", "chain_valid": False,
            "errors": ["invalid_input:" + type(exc).__name__],
            "head_entry_sha256": None, "decision": "HOLD", "authorization": "DENY",
        }
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["chain_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
