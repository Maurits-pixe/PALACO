#!/usr/bin/env python3
"""GO-12H integrity verification for PALACO v1.0.0."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ATTESTATION = ROOT / "evidence" / "manifests" / "GO-12-V1.0.0-TAG-ATTESTATION.json"


def fail(message: str) -> None:
    print(f"GO-12H TAG INTEGRITY: FAIL - {message}")
    raise SystemExit(1)


def github_json(url: str):
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PALACO-GO-12H-Tag-Integrity",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        fail(f"GitHub request failed for {url}: HTTP {exc.code}")
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        fail(f"GitHub request failed for {url}: {exc}")


def main() -> None:
    a = json.loads(ATTESTATION.read_text(encoding="utf-8"))

    if a.get("schema") != "palaco.tag-attestation.v1":
        fail("unexpected attestation schema")
    if a.get("repository") != "Maurits-pixe/PALACO":
        fail("unexpected repository")
    if a.get("tag") != "v1.0.0":
        fail("unexpected tag name")

    expected_tag_object = a["annotated_tag_object_sha"]
    expected_target = a["target_commit_sha"]

    ref = github_json(
        "https://api.github.com/repos/Maurits-pixe/PALACO/git/ref/tags/v1.0.0"
    )
    if ref.get("ref") != "refs/tags/v1.0.0":
        fail("tag ref name changed")
    ref_object = ref.get("object", {})
    if ref_object.get("type") != "tag":
        fail("v1.0.0 is no longer an annotated tag")
    if ref_object.get("sha") != expected_tag_object:
        fail(
            "annotated tag object changed: "
            f"expected {expected_tag_object}, got {ref_object.get('sha')}"
        )

    tag = github_json(
        f"https://api.github.com/repos/Maurits-pixe/PALACO/git/tags/{expected_tag_object}"
    )
    if tag.get("tag") != "v1.0.0":
        fail("tag object name changed")
    if tag.get("message", "").strip() != a["tag_message"]:
        fail("tag message changed")
    target = tag.get("object", {})
    if target.get("type") != "commit":
        fail("tag no longer targets a commit")
    if target.get("sha") != expected_target:
        fail(
            f"tag target changed: expected {expected_target}, got {target.get('sha')}"
        )

    expected_sig = a["verification"]["tag_signature"]
    sig = tag.get("verification", {})
    if sig.get("verified") is not expected_sig["verified"]:
        fail("tag signature verification state changed")
    if sig.get("reason") != expected_sig["reason"]:
        fail("tag signature verification reason changed")

    run_id = a["verification"]["workflow_run_id"]
    run = github_json(
        f"https://api.github.com/repos/Maurits-pixe/PALACO/actions/runs/{run_id}"
    )
    if run.get("name") != "GO-12 Immutable v1.0.0 Tag":
        fail("GO-12 evidence run identity changed")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        fail("GO-12 evidence run is not completed/success")

    commit = github_json(
        f"https://api.github.com/repos/Maurits-pixe/PALACO/commits/{expected_target}"
    )
    if commit.get("sha") != expected_target:
        fail("release commit cannot be resolved")

    rulesets = github_json("https://api.github.com/repos/Maurits-pixe/PALACO/rulesets")
    tag_rulesets = [
        item for item in rulesets
        if item.get("target") == "tag" and item.get("enforcement") == "active"
    ]

    print("GO-12H TAG INTEGRITY: PASS")
    print("tag=v1.0.0")
    print(f"annotated_tag_object={expected_tag_object}")
    print(f"target_commit={expected_target}")
    print("go12_run=COMPLETED_SUCCESS")
    print("tag_signature=UNSIGNED_PRESERVED")
    print(
        "server_side_tag_ruleset="
        + ("ACTIVE" if tag_rulesets else "ABSENT")
    )
    print(
        "preventive_immutability="
        + ("ENFORCED" if tag_rulesets else "OPEN_ADMIN_ACTION")
    )


if __name__ == "__main__":
    main()
