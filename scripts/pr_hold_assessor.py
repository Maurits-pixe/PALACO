#!/usr/bin/env python3
"""Offline, fail-closed advisory assessment of a PALACO change candidate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA = "palaco.pr-assessment.v2"
REQUIRED = ("repository", "head_sha", "checks", "reviews", "evidence")
CHECK_STATES = {"success", "failure", "pending", "missing"}
REVIEW_STATES = {"approved", "changes_requested", "pending", "missing"}


def is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(
        character in "0123456789abcdef" for character in value
    )


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def assess(data: object) -> dict:
    reasons: list[str] = []
    if not isinstance(data, dict):
        reasons.append("snapshot_not_object")
    else:
        for key in REQUIRED:
            if key not in data:
                reasons.append("missing_" + key)
        repo = data.get("repository")
        if (not isinstance(repo, str) or repo.count("/") != 1 or
                any(not part or part.strip() != part for part in repo.split("/"))):
            reasons.append("invalid_repository")
        sha = data.get("head_sha")
        if not is_hex(sha, 40):
            reasons.append("invalid_head_sha")
        checks = data.get("checks")
        if not isinstance(checks, dict) or not checks:
            reasons.append("checks_absent")
        else:
            for name, state in checks.items():
                if (not isinstance(name, str) or not name.strip() or
                        not isinstance(state, str) or state not in CHECK_STATES):
                    reasons.append("invalid_check_entry")
                    continue
                if state != "success":
                    reasons.append("check_not_success:" + name)
        reviews = data.get("reviews")
        if not isinstance(reviews, str) or reviews not in REVIEW_STATES:
            reasons.append("invalid_reviews")
        elif reviews != "approved":
            reasons.append("review_not_approved")
        evidence = data.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            reasons.append("evidence_absent")
        else:
            seen = set()
            for item in evidence:
                if (not isinstance(item, dict) or
                        set(item) != {"kind", "head_sha", "artifact_sha256"}):
                    reasons.append("invalid_evidence")
                    continue
                kind = item["kind"]
                digest = item["artifact_sha256"]
                if not isinstance(kind, str) or not kind.strip() or not is_hex(digest, 64):
                    reasons.append("invalid_evidence")
                if item["head_sha"] != sha:
                    reasons.append("evidence_head_mismatch")
                if isinstance(digest, str):
                    if digest in seen:
                        reasons.append("duplicate_evidence_digest")
                    seen.add(digest)
        if data.get("go13_release_authorized") is not True:
            reasons.append("go13_not_authorized")
    return {
        "schema": SCHEMA,
        "decision": "HOLD",
        "authorization": "DENY",
        "reasons": sorted(set(reasons)),
        "technical_inputs_complete": not reasons,
        "note": "Advisory input consistency only; independent evidence verification and human authority required."
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Local JSON input without secrets")
    args = parser.parse_args(argv)
    try:
        data = json.loads(
            args.snapshot.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({
            "schema": SCHEMA, "decision": "HOLD", "authorization": "DENY",
            "reasons": ["unreadable_snapshot"], "detail": type(exc).__name__
        }, sort_keys=True))
        return 2
    print(json.dumps(assess(data), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
