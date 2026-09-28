#!/usr/bin/env python3
"""Verify the PALACO GO-11 release manifest."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "manifests" / "GO-11-RELEASE-MANIFEST.json"
CHECKSUM = ROOT / "evidence" / "manifests" / "GO-11-RELEASE-MANIFEST.sha256"

ALLOWED_POST_SUBJECT_PATHS = {
    "evidence/manifests/GO-11-RELEASE-MANIFEST.json",
    "evidence/manifests/GO-11-RELEASE-MANIFEST.sha256",
    "tools/verify_go11_release_manifest.py",
    ".github/workflows/go-11-release-manifest.yml",
}


def fail(message: str) -> None:
    print(f"GO-11 RELEASE MANIFEST: FAIL - {message}")
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


def github_json(url: str, allow_404: bool = False) -> dict | None:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PALACO-GO-11-Release-Manifest",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        fail(f"GitHub request failed for {url}: HTTP {exc.code}")
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        fail(f"GitHub request failed for {url}: {exc}")


def subject_blob_sha(subject: str, path: str) -> str:
    line = git("ls-tree", subject, "--", path)
    if not line:
        fail(f"release-critical path missing at subject: {path}")
    parts = line.split()
    if len(parts) < 4 or parts[1] != "blob":
        fail(f"release-critical path is not a blob at subject: {path}")
    return parts[2]


def main() -> None:
    manifest_bytes = MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)

    checksum_parts = CHECKSUM.read_text(encoding="utf-8").strip().split()
    if len(checksum_parts) != 2:
        fail("malformed companion checksum")
    expected_digest, checksum_name = checksum_parts
    if checksum_name != MANIFEST.name:
        fail("checksum filename does not identify release manifest")
    actual_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_digest != expected_digest:
        fail(f"manifest SHA-256 mismatch: expected {expected_digest}, got {actual_digest}")

    if manifest.get("schema") != "palaco.release-manifest.v1":
        fail("unexpected release manifest schema")
    if manifest.get("gate") != "GO-11":
        fail("unexpected gate")
    if manifest.get("repository") != "Maurits-pixe/PALACO":
        fail("unexpected repository")
    if manifest.get("version") != "1.0.0":
        fail("unexpected release version")
    if manifest.get("planned_tag") != "v1.0.0":
        fail("unexpected planned tag")

    subject = manifest["release_subject"]
    subject_sha = subject["commit_sha"]
    expected_tree = subject["tree_sha"]

    git("cat-file", "-e", f"{subject_sha}^{{commit}}")
    actual_tree = git("show", "-s", "--format=%T", subject_sha)
    if actual_tree != expected_tree:
        fail(f"release subject tree mismatch: expected {expected_tree}, got {actual_tree}")

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", subject_sha, "HEAD"],
        cwd=ROOT,
        check=False,
    )
    if ancestor.returncode != 0:
        fail("release subject is not an ancestor of manifest container HEAD")

    changed = {
        line
        for line in git("diff", "--name-only", f"{subject_sha}..HEAD").splitlines()
        if line
    }
    unexpected = changed - ALLOWED_POST_SUBJECT_PATHS
    missing_expected = {
        "evidence/manifests/GO-11-RELEASE-MANIFEST.json",
        "evidence/manifests/GO-11-RELEASE-MANIFEST.sha256",
        "tools/verify_go11_release_manifest.py",
        ".github/workflows/go-11-release-manifest.yml",
    } - changed
    if unexpected:
        fail("non-GO-11 changes exist after release subject: " + ", ".join(sorted(unexpected)))
    if missing_expected:
        fail("expected GO-11 container files missing from post-subject diff: " + ", ".join(sorted(missing_expected)))

    commit_api = github_json(
        f"https://api.github.com/repos/Maurits-pixe/PALACO/commits/{subject_sha}"
    )
    if commit_api is None:
        fail("release subject commit not found in GitHub API")
    verification = commit_api.get("commit", {}).get("verification", {})
    expected_verification = subject["github_signature_verification"]
    if verification.get("verified") is not expected_verification["verified"]:
        fail("release subject signature verification state changed")
    if verification.get("reason") != expected_verification["reason"]:
        fail("release subject signature verification reason changed")
    if commit_api.get("commit", {}).get("tree", {}).get("sha") != expected_tree:
        fail("GitHub API tree does not match release manifest")

    for item in manifest["release_critical_blobs"]:
        actual = subject_blob_sha(subject_sha, item["path"])
        if actual != item["blob_sha"]:
            fail(
                f"release-critical blob mismatch for {item['path']}: "
                f"expected {item['blob_sha']}, got {actual}"
            )

    for item in manifest["current_head_evidence"]:
        run_id = item["run_id"]
        run = github_json(
            f"https://api.github.com/repos/Maurits-pixe/PALACO/actions/runs/{run_id}"
        )
        if run is None:
            fail(f"evidence run missing: {run_id}")
        expected = {
            "name": item["name"],
            "head_sha": subject_sha,
            "status": "completed",
            "conclusion": "success",
        }
        for field, value in expected.items():
            if run.get(field) != value:
                fail(
                    f"run {run_id} {field} mismatch: expected {value!r}, got {run.get(field)!r}"
                )

    workspace = manifest["workspace"]
    cargo = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    package = cargo.get("workspace", {}).get("package", {})
    if package.get("version") != manifest["version"]:
        fail("Cargo workspace version does not match release manifest")
    if package.get("edition") != workspace["edition"]:
        fail("Cargo edition does not match release manifest")
    if package.get("license") != workspace["license"]:
        fail("Cargo license does not match release manifest")
    if package.get("publish") is not False or workspace["publish"] is not False:
        fail("package publication must remain disabled at GO-11")

    members = [Path(value).name for value in cargo.get("workspace", {}).get("members", [])]
    if members != workspace["crates"]:
        fail(f"workspace crate list mismatch: {members!r}")

    docs = []
    for base in [
        ROOT / "docs" / "constitution" / "PCS",
        ROOT / "docs" / "architecture" / "PAS",
        ROOT / "docs" / "implementation" / "PIS",
        ROOT / "docs" / "operations" / "POS",
        ROOT / "docs" / "ecosystem",
    ]:
        docs.extend(path for path in base.glob("*.md") if path.name != ".gitkeep")
    expected_count = manifest["canonical_content"]["substantive_imported_artifacts"]
    if len(docs) != expected_count:
        fail(f"canonical artifact count mismatch: expected {expected_count}, got {len(docs)}")

    if manifest["release_state"]["release_blockers"]:
        fail("release manifest contains unresolved release blockers")
    if manifest["release_state"]["technical_audit"] != "PASS":
        fail("technical audit is not PASS")
    if manifest["release_state"]["license_resolution"] != "RATIFIED_MIT_OR_APACHE_2_0":
        fail("license resolution is not the ratified GO-10R state")
    if manifest["release_state"]["package_publication"] != "DISABLED":
        fail("release manifest must preserve disabled package publication")

    tag = github_json(
        "https://api.github.com/repos/Maurits-pixe/PALACO/git/ref/tags/v1.0.0",
        allow_404=True,
    )
    if tag is not None:
        fail("v1.0.0 tag already exists before GO-12")

    print("GO-11 RELEASE MANIFEST: PASS")
    print(f"release_subject={subject_sha}")
    print(f"release_subject_tree={expected_tree}")
    print(f"manifest_sha256={actual_digest}")
    print("version=1.0.0")
    print("license=MIT OR Apache-2.0")
    print("canonical_artifacts=28")
    print("release_blockers=NONE")
    print("package_publication=DISABLED")
    print("planned_tag=v1.0.0")
    print("go12=ELIGIBLE")
    print("subject_signature=UNSIGNED_PRESERVED")
    print("post_subject_changes=GO11_EVIDENCE_ONLY")


if __name__ == "__main__":
    main()
