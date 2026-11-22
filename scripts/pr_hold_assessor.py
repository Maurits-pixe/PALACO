#!/usr/bin/env python3
"""Offline, fail-closed advisory assessment of a PALACO change candidate.

Input is a local JSON evidence snapshot. No GitHub access, secrets, execution,
authorization, deployment, or changes to branch protection are performed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED = ("repository", "head_sha", "checks", "reviews", "evidence")
CHECK_STATES = {"success", "failure", "pending", "missing"}
REVIEW_STATES = {"approved", "changes_requested", "pending", "missing"}


def assess(data: object) -> dict:
    reasons: list[str] = []
    if not isinstance(data, dict):
        return {"schema": "palaco.pr-assessment.v1", "decision": "HOLD",
                "authorization": "DENY", "reasons": ["snapshot_not_object"]}
    for key in REQUIRED:
        if key not in data:
            reasons.append("missing_" + key)
    repo = data.get("repository")
    if not isinstance(repo, str) or "/" not in repo or not all(repo.split("/", 1)):
        reasons.append("invalid_repository")
    sha = data.get("head_sha")
    if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        reasons.append("invalid_head_sha")
    checks = data.get("checks")
    if not isinstance(checks, dict) or not checks:
        reasons.append("checks_absent")
    else:
        for name, state in checks.items():
            if not isinstance(name, str) or not name.strip() or state not in CHECK_STATES:
                reasons.append("invalid_check_entry")
                break
            if state != "success":
                reasons.append("check_not_success:" + name)
    reviews = data.get("reviews")
    if reviews not in REVIEW_STATES:
        reasons.append("invalid_reviews")
    elif reviews != "approved":
        reasons.append("review_not_approved")
    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        reasons.append("evidence_absent")
    elif any(not isinstance(item, str) or not item.strip() for item in evidence):
        reasons.append("invalid_evidence")
    if data.get("go13_release_authorized") is not True:
        reasons.append("go13_not_authorized")
    # This assessor is advisory only, even when every input passes.
    return {"schema": "palaco.pr-assessment.v1", "decision": "HOLD",
            "authorization": "DENY", "reasons": sorted(set(reasons)),
            "technical_inputs_complete": not reasons,
            "note": "Advisory only; human governance and independent verification required."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Local JSON input; do not include secrets")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"schema": "palaco.pr-assessment.v1", "decision": "HOLD",
                          "authorization": "DENY", "reasons": ["unreadable_snapshot"],
                          "detail": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(assess(data), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
