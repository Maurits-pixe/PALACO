#!/usr/bin/env python3
"""Offline, fail-closed advisory assessment of a PALACO change candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

SCHEMA = "palaco.pr-assessment.v2"
REQUIRED = ("repository", "head_sha", "checks", "reviews", "evidence")
CHECK_STATES = {"success", "failure", "pending", "missing"}
REVIEW_STATES = {"approved", "changes_requested", "pending", "missing"}
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


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



def verify_local_artifact(root: Path, relative: object, expected: object) -> str | None:
    """Verify a bounded regular file beneath root, refusing symlinks.

    Secure traversal requires POSIX O_NOFOLLOW plus directory-relative opens.
    Unsupported platforms fail closed instead of silently following links.
    """
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        return "invalid_artifact_path"
    if not is_hex(expected, 64):
        return "invalid_artifact_digest"
    if (relative.startswith("/") or "\\" in relative or ":" in relative or
            any(part in ("", ".", "..") for part in relative.split("/"))):
        return "invalid_artifact_path"
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        return "secure_file_open_unsupported"
    descriptors: list[int] = []
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        parts = relative.split("/")
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=fd)
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARTIFACT_BYTES:
            return "invalid_artifact_file"
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                return "artifact_too_large"
            digest.update(chunk)
        if os.fstat(fd).st_size != total:
            return "artifact_size_changed"
        return None if digest.hexdigest() == expected else "artifact_digest_mismatch"
    except (OSError, ValueError):
        return "artifact_unreadable"
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)



def canonical_digest(payload: object) -> str:
    """Deterministic UTF-8 digest; never a signature or trust attestation."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evidence_manifest(data: object) -> dict | None:
    """Build a stable manifest solely from well-formed, locally supplied records."""
    if not isinstance(data, dict):
        return None
    repository, head_sha, items = (
        data.get("repository"), data.get("head_sha"), data.get("evidence")
    )
    if not isinstance(repository, str) or not is_hex(head_sha, 40):
        return None
    if not isinstance(items, list) or not items:
        return None
    entries = []
    for item in items:
        if (not isinstance(item, dict) or
                set(item) != {"kind", "head_sha", "artifact_sha256", "path"} or
                not isinstance(item["kind"], str) or not item["kind"].strip() or
                not isinstance(item["path"], str) or not item["path"] or
                not is_hex(item["artifact_sha256"], 64) or
                item["head_sha"] != head_sha):
            return None
        entries.append(dict(item))
    entries.sort(key=lambda entry: (
        entry["path"], entry["kind"], entry["artifact_sha256"], entry["head_sha"]
    ))
    manifest = {
        "schema": "palaco.pr-evidence-manifest.v1",
        "repository": repository,
        "head_sha": head_sha,
        "entries": entries,
    }
    return {"manifest": manifest, "manifest_sha256": canonical_digest(manifest)}


def seal_advisory_report(data: object, result: dict) -> dict:
    """Add reproducible identifiers without elevating the authority of inputs."""
    report = dict(result)
    try:
        manifest = evidence_manifest(data)
        report["manifest_sha256"] = (
            manifest["manifest_sha256"] if manifest is not None else None
        )
        report["report_sha256"] = canonical_digest(report)
    except (TypeError, ValueError, OverflowError, RecursionError):
        report["manifest_sha256"] = None
        report["technical_inputs_complete"] = False
        report["reasons"] = sorted(set(report["reasons"] + ["unhashable_snapshot"]))
        report["report_sha256"] = None
    return report


def assess(data: object, evidence_root: Path | None = None) -> dict:
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
                        set(item) != {"kind", "head_sha", "artifact_sha256", "path"}):
                    reasons.append("invalid_evidence")
                    continue
                kind = item["kind"]
                digest = item["artifact_sha256"]
                if not isinstance(kind, str) or not kind.strip() or not is_hex(digest, 64):
                    reasons.append("invalid_evidence")
                if item["head_sha"] != sha:
                    reasons.append("evidence_head_mismatch")
                if evidence_root is None:
                    reasons.append("evidence_not_verified")
                else:
                    issue = verify_local_artifact(evidence_root, item.get("path"), digest)
                    if issue is not None:
                        reasons.append(issue)
                if isinstance(digest, str):
                    if digest in seen:
                        reasons.append("duplicate_evidence_digest")
                    seen.add(digest)
        if data.get("go13_release_authorized") is not True:
            reasons.append("go13_not_authorized")
    return seal_advisory_report(data, {
        "schema": SCHEMA,
        "decision": "HOLD",
        "authorization": "DENY",
        "reasons": sorted(set(reasons)),
        "technical_inputs_complete": not reasons,
        "note": "Advisory input consistency only; independent evidence verification and human authority required."
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Local JSON input without secrets")
    parser.add_argument("--evidence-root", type=Path, default=None,
                        help="Local artifact directory (required for verification)")
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
    print(json.dumps(assess(data, args.evidence_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
