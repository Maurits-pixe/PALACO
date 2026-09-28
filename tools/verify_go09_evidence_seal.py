#!/usr/bin/env python3
"""Verify the PALACO GO-09 evidence seal without upgrading its authority claims."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "manifests" / "GO-09-EVIDENCE-SEAL.json"
CHECKSUM = ROOT / "evidence" / "manifests" / "GO-09-EVIDENCE-SEAL.sha256"


def fail(message: str) -> None:
    print(f"GO-09 EVIDENCE SEAL: FAIL - {message}")
    raise SystemExit(1)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        fail(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def github_json(url: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PALACO-GO-09-Evidence-Seal",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        fail(f"GitHub verification request failed for {url}: {exc}")


def main() -> None:
    manifest_bytes = MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)

    checksum_parts = CHECKSUM.read_text(encoding="utf-8").strip().split()
    if len(checksum_parts) != 2:
        fail("malformed companion checksum")
    expected_digest, checksum_name = checksum_parts
    if checksum_name != MANIFEST.name:
        fail("checksum filename does not identify the manifest")
    actual_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_digest != expected_digest:
        fail(f"manifest SHA-256 mismatch: expected {expected_digest}, got {actual_digest}")

    if manifest.get("schema") != "palaco.evidence-seal.v1":
        fail("unexpected seal schema")
    if manifest.get("gate") != "GO-09":
        fail("unexpected gate identifier")
    if manifest.get("repository") != "Maurits-pixe/PALACO":
        fail("unexpected repository identity")

    subject = manifest["subject"]
    subject_sha = subject["commit_sha"]
    subject_tree = subject["tree_sha"]

    git("cat-file", "-e", f"{subject_sha}^{{commit}}")
    actual_tree = git("show", "-s", "--format=%T", subject_sha)
    if actual_tree != subject_tree:
        fail(f"subject tree mismatch: expected {subject_tree}, got {actual_tree}")

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", subject_sha, "HEAD"],
        cwd=ROOT,
        check=False,
    )
    if ancestor.returncode != 0:
        fail("sealed subject is not an ancestor of the seal commit")

    commit_api = github_json(
        f"https://api.github.com/repos/Maurits-pixe/PALACO/commits/{subject_sha}"
    )
    verification = commit_api.get("commit", {}).get("verification", {})
    expected_verification = subject["github_signature_verification"]
    if verification.get("verified") is not expected_verification["verified"]:
        fail("GitHub commit signature verification state changed")
    if verification.get("reason") != expected_verification["reason"]:
        fail("GitHub commit signature verification reason changed")
    if commit_api.get("commit", {}).get("tree", {}).get("sha") != subject_tree:
        fail("GitHub commit API tree does not match sealed subject tree")

    for item in manifest["evidence"]:
        run_id = item["run_id"]
        run = github_json(
            f"https://api.github.com/repos/Maurits-pixe/PALACO/actions/runs/{run_id}"
        )
        checks = {
            "name": item["name"],
            "head_sha": subject_sha,
            "status": "completed",
            "conclusion": "success",
        }
        for field, expected in checks.items():
            actual = run.get(field)
            if actual != expected:
                fail(
                    f"run {run_id} {field} mismatch: expected {expected!r}, got {actual!r}"
                )

    print("GO-09 EVIDENCE SEAL: PASS")
    print(f"subject_commit={subject_sha}")
    print(f"subject_tree={subject_tree}")
    print(f"manifest_sha256={actual_digest}")
    print("evidence_runs=5 completed/success and bound to subject commit")
    print("github_commit_signature=unsigned (preserved, not upgraded)")


if __name__ == "__main__":
    main()
