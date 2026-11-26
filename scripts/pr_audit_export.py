#!/usr/bin/env python3
"""GO-20 v16: strict, offline audit-row export adapter for disposable CI.

Reads newline-delimited JSON from an explicitly supplied local file; never
connects to a database. Generated anchor is SELF-REPORTED, not independent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_audit_integrity import SCHEMA, MAX_ENTRIES, ZERO, canonical_hash, is_hex, unique_pairs, verify_export

ROW_KEYS = {"id", "operation", "actor_role", "tenant_role", "entry_sha256"}


def build_export(rows: object) -> dict:
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ENTRIES:
        raise ValueError("invalid_audit_row_count")
    events = []
    previous = ZERO
    last_source_id = 0
    source_ids = []
    for index, source in enumerate(rows, 1):
        if not isinstance(source, dict) or set(source) != ROW_KEYS:
            raise ValueError("invalid_source_row")
        source_id = source["id"]
        if type(source_id) is not int or source_id <= last_source_id:
            raise ValueError("source_id_not_strictly_increasing")
        if (source["operation"] not in ("INSERT", "UPDATE", "DELETE") or
                not isinstance(source["actor_role"], str) or not source["actor_role"] or
                not isinstance(source["tenant_role"], str) or not source["tenant_role"] or
                not is_hex(source["entry_sha256"], 64)):
            raise ValueError("invalid_source_row_fields")
        event = {
            "id": index, "operation": source["operation"],
            "actor_role": source["actor_role"], "tenant_role": source["tenant_role"],
            "entry_sha256": source["entry_sha256"],
            "previous_sha256": previous,
        }
        event["event_sha256"] = canonical_hash(event)
        events.append(event)
        previous = event["event_sha256"]
        last_source_id = source_id
        source_ids.append(source_id)
    payload = {"schema": SCHEMA, "events": events}
    manifest = {
        "schema": "palaco.go20-export-manifest.v1",
        "event_count": len(events),
        "source_ids": source_ids,
        "export_sha256": canonical_hash(payload),
        "calculated_head_sha256": previous,
        "independently_attested": False,
        "decision": "HOLD",
        "authorization": "DENY",
    }
    if not verify_export(payload, previous)["integrity_valid"]:
        raise ValueError("generated_export_invalid")
    return {"export": payload, "manifest": manifest}


def read_rows(text: str) -> list:
    if len(text.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("audit_input_too_large")
    if not text.strip():
        raise ValueError("empty_audit_input")
    rows = []
    for line in text.splitlines():
        if not line.strip():
            raise ValueError("blank_row")
        rows.append(json.loads(line, object_pairs_hook=unique_pairs))
        if len(rows) > MAX_ENTRIES:
            raise ValueError("too_many_rows")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-ndjson", type=Path, required=True)
    parser.add_argument("--output-export", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.output_export == args.output_manifest:
        parser.error("export and manifest paths must differ")
    try:
        if args.output_export.exists() or args.output_manifest.exists():
            raise ValueError("output_exists")
        bundle = build_export(read_rows(args.input_ndjson.read_text(encoding="utf-8")))
        # Outputs are advisory artifacts; no implicit trust or authority.
        for path, content in (
            (args.output_export, bundle["export"]),
            (args.output_manifest, bundle["manifest"]),
        ):
            with path.open("x", encoding="utf-8") as handle:
                json.dump(content, handle, sort_keys=True, indent=2, ensure_ascii=False)
                handle.write("\n")
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        print("GO-20 audit export: HOLD/DENY - " + type(exc).__name__ + ": " + str(exc))
        return 2
    print("GO-20 audit export: generated untrusted local snapshot; HOLD/DENY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
