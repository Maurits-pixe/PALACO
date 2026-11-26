#!/usr/bin/env python3
"""GO-20 v17: independent signed audit checkpoint and completeness verifier.

Read-only. An externally provisioned trust registry and minimum checkpoint
revision are required. Even valid signatures confer no PALACO authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_attestation_chain import verify_signature
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs, verify_export

CHECKPOINT_SCHEMA = "palaco.go20-signed-audit-checkpoint.v1"
TRUST_SCHEMA = "palaco.go20-audit-trust.v1"
MANIFEST_SCHEMA = "palaco.go20-export-manifest.v1"


def verify_checkpoint(export: object, manifest: object, checkpoint: object,
                      trusted_keys: object, minimum_revision: object) -> dict:
    errors: list[str] = []
    signed = None
    signer_id = None
    if not isinstance(trusted_keys, dict) or set(trusted_keys) != {"schema", "keys"} or trusted_keys.get("schema") != TRUST_SCHEMA:
        errors.append("invalid_external_trust_registry")
        keys = {}
    else:
        keys = trusted_keys.get("keys")
        if not isinstance(keys, dict) or not keys:
            errors.append("invalid_external_trust_registry")
            keys = {}
    for identity, record in keys.items():
        if (not isinstance(identity, str) or not identity or
                not isinstance(record, dict) or set(record) != {"public_key_hex", "status"} or
                not is_hex(record["public_key_hex"], 64) or record["status"] not in ("active", "revoked")):
            errors.append("invalid_external_key_record")
    if type(minimum_revision) is not int or minimum_revision < 0:
        errors.append("invalid_minimum_revision")
    if not isinstance(checkpoint, dict) or set(checkpoint) != {
        "payload", "signer_key_id", "signature_ed25519_hex"
    }:
        errors.append("invalid_signed_checkpoint")
    else:
        signed = checkpoint["payload"]
        signer_id = checkpoint["signer_key_id"]
        if not isinstance(signed, dict) or set(signed) != {
            "schema", "revision", "repository", "export_sha256", "head_sha256",
            "event_count", "source_ids_sha256", "first_source_id", "last_source_id"
        } or signed.get("schema") != CHECKPOINT_SCHEMA:
            errors.append("invalid_checkpoint_payload")
            signed = None
        if not isinstance(signer_id, str) or signer_id not in keys:
            errors.append("untrusted_checkpoint_signer")
        elif isinstance(keys[signer_id], dict) and keys[signer_id].get("status") == "revoked":
            errors.append("revoked_checkpoint_signer")
        if not is_hex(checkpoint["signature_ed25519_hex"], 128):
            errors.append("invalid_signature_encoding")
        elif (signed is not None and isinstance(signer_id, str) and
              signer_id in keys and isinstance(keys[signer_id], dict) and
              is_hex(keys[signer_id].get("public_key_hex"), 64)):
            statement = {
                "schema": "palaco.go20-audit-checkpoint-signature.v1",
                "payload_sha256": canonical_hash(signed),
            }
            issue = verify_signature(keys[signer_id]["public_key_hex"],
                                     checkpoint["signature_ed25519_hex"], statement)
            if issue:
                errors.append(issue)

    if not isinstance(manifest, dict) or set(manifest) != {
        "schema", "event_count", "source_ids", "export_sha256",
        "calculated_head_sha256", "independently_attested", "decision", "authorization"
    } or manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append("invalid_manifest")
        manifest = None
    else:
        ids = manifest["source_ids"]
        if (not isinstance(ids, list) or not ids or len(ids) > 10000 or
                any(type(v) is not int or v <= 0 for v in ids) or
                any(a >= b for a, b in zip(ids, ids[1:])) or
                type(manifest["event_count"]) is not int or
                manifest["event_count"] != len(ids) or
                not is_hex(manifest["export_sha256"], 64) or
                not is_hex(manifest["calculated_head_sha256"], 64) or
                manifest["independently_attested"] is not False or
                manifest["decision"] != "HOLD" or manifest["authorization"] != "DENY"):
            errors.append("invalid_manifest_fields")

    if signed is not None:
        if (type(signed["revision"]) is not int or signed["revision"] < 0 or
                (type(minimum_revision) is int and signed["revision"] < minimum_revision)):
            errors.append("checkpoint_revision_rollback")
        if signed["repository"] != "Maurits-pixe/PALACO":
            errors.append("checkpoint_repository_mismatch")
        if (not is_hex(signed["export_sha256"], 64) or
                not is_hex(signed["head_sha256"], 64) or
                not is_hex(signed["source_ids_sha256"], 64) or
                type(signed["event_count"]) is not int or signed["event_count"] < 1 or
                type(signed["first_source_id"]) is not int or
                type(signed["last_source_id"]) is not int):
            errors.append("invalid_checkpoint_fields")
    if manifest is not None and signed is not None:
        ids = manifest.get("source_ids")
        if isinstance(ids, list) and ids and all(type(v) is int for v in ids):
            if (canonical_hash(ids) != signed["source_ids_sha256"] or
                    ids[0] != signed["first_source_id"] or
                    ids[-1] != signed["last_source_id"] or
                    len(ids) != signed["event_count"]):
                errors.append("signed_source_completeness_mismatch")
        else:
            errors.append("invalid_source_ids")
        if (manifest.get("export_sha256") != signed["export_sha256"] or
                manifest.get("calculated_head_sha256") != signed["head_sha256"]):
            errors.append("signed_export_manifest_mismatch")
    if signed is not None:
        try:
            if canonical_hash(export) != signed["export_sha256"]:
                errors.append("signed_export_digest_mismatch")
        except (TypeError, ValueError, RecursionError, OverflowError):
            errors.append("invalid_export_encoding")
        integrity = verify_export(export, signed["head_sha256"])
        errors.extend(integrity["errors"])
        if isinstance(export, dict) and isinstance(export.get("events"), list):
            if len(export["events"]) != signed["event_count"]:
                errors.append("signed_event_count_mismatch")
    return {
        "schema": "palaco.go20-audit-checkpoint-verdict.v1",
        "checkpoint_valid": not errors,
        "errors": sorted(set(errors)),
        "decision": "HOLD",
        "authorization": "DENY",
        "note": "Signer trust and minimum revision must be independently provisioned; no production authorization.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--trusted-keys", type=Path, required=True)
    parser.add_argument("--minimum-revision", type=int, required=True)
    args = parser.parse_args()
    try:
        def read(path: Path) -> object:
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
        result = verify_checkpoint(read(args.export), read(args.manifest),
                                   read(args.checkpoint), read(args.trusted_keys),
                                   args.minimum_revision)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        result = {
            "schema": "palaco.go20-audit-checkpoint-verdict.v1",
            "checkpoint_valid": False, "errors": ["invalid_input:" + type(exc).__name__],
            "decision": "HOLD", "authorization": "DENY",
        }
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["checkpoint_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
