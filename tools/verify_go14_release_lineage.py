#!/usr/bin/env python3
"""GO-14 Release Lineage Continuity verifier.

GO-14 does not alter the v1.0.0 release. It proves that current development
remains descended from the sealed release line and that main retains the
required GO-13 Standards Conformance gate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

REPOSITORY = "Maurits-pixe/PALACO"
RELEASE_TAG = "v1.0.0"
RELEASE_TAG_OBJECT = "2604d6f1c89660b22d08605722a6916f321cdd73"
RELEASE_COMMIT = "5283a560dc9d410fa778d69f93bb339dbafbf5fe"
REQUIRED_STATUS = "standards-conformance"
MAIN_REF = "refs/heads/main"


def fail(message: str) -> None:
    print(f"GO-14 RELEASE LINEAGE: FAIL - {message}")
    raise SystemExit(1)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def github_json(url: str):
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PALACO-GO-14-Release-Lineage",
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
    # Release target must still be in the checked-out history.
    exists = git("cat-file", "-e", f"{RELEASE_COMMIT}^{{commit}}")
    if exists.returncode != 0:
        fail("v1.0.0 release commit is not available in local history")

    lineage = git("merge-base", "--is-ancestor", RELEASE_COMMIT, "HEAD")
    if lineage.returncode != 0:
        fail("current candidate is not descended from PALACO Foundation v1.0.0")

    # The public tag identity must remain unchanged.
    ref = github_json(
        f"https://api.github.com/repos/{REPOSITORY}/git/ref/tags/{RELEASE_TAG}"
    )
    ref_object = ref.get("object", {})
    if ref_object.get("type") != "tag":
        fail("v1.0.0 is no longer an annotated tag")
    if ref_object.get("sha") != RELEASE_TAG_OBJECT:
        fail(
            "v1.0.0 tag object changed: "
            f"expected {RELEASE_TAG_OBJECT}, got {ref_object.get('sha')}"
        )

    tag = github_json(
        f"https://api.github.com/repos/{REPOSITORY}/git/tags/{RELEASE_TAG_OBJECT}"
    )
    target = tag.get("object", {})
    if target.get("type") != "commit" or target.get("sha") != RELEASE_COMMIT:
        fail("v1.0.0 no longer targets the canonical release commit")

    # main must retain an active branch ruleset requiring GO-13.
    rulesets = github_json(f"https://api.github.com/repos/{REPOSITORY}/rulesets")
    main_guard = None
    for item in rulesets:
        if item.get("target") != "branch" or item.get("enforcement") != "active":
            continue
        detail = github_json(
            f"https://api.github.com/repos/{REPOSITORY}/rulesets/{item['id']}"
        )
        includes = set(
            detail.get("conditions", {}).get("ref_name", {}).get("include", [])
        )
        if MAIN_REF not in includes:
            continue

        required = None
        for rule in detail.get("rules", []):
            if rule.get("type") == "required_status_checks":
                required = rule.get("parameters", {})
                break
        if not required:
            continue

        contexts = {
            check.get("context")
            for check in required.get("required_status_checks", [])
        }
        if (
            REQUIRED_STATUS in contexts
            and required.get("strict_required_status_checks_policy") is True
            and not detail.get("bypass_actors", [])
        ):
            main_guard = detail
            break

    if main_guard is None:
        fail(
            "main lacks an active strict no-bypass ruleset requiring "
            f"{REQUIRED_STATUS}"
        )

    go13 = ROOT / ".github" / "workflows" / "go-13-standards-conformance.yml"
    if not go13.is_file():
        fail("GO-13 workflow is missing")
    go13_text = go13.read_text(encoding="utf-8")
    if "standards-conformance:" not in go13_text:
        fail("GO-13 workflow no longer defines the required job context")

    # Tag-ruleset hardening is still tracked separately as GO-12I.
    active_tag_rulesets = [
        item
        for item in rulesets
        if item.get("target") == "tag" and item.get("enforcement") == "active"
    ]

    print("GO-14 RELEASE LINEAGE: PASS")
    print(f"release_tag={RELEASE_TAG}")
    print(f"release_tag_object={RELEASE_TAG_OBJECT}")
    print(f"release_commit={RELEASE_COMMIT}")
    print("current_candidate_descends_from_release=YES")
    print(f"main_required_status={REQUIRED_STATUS}")
    print(f"main_ruleset_id={main_guard['id']}")
    print("main_ruleset_strict=YES")
    print("main_ruleset_bypass=NONE")
    print(
        "server_side_tag_ruleset="
        + ("ACTIVE" if active_tag_rulesets else "OPEN_GO_12I_ADMIN_ACTION")
    )
    print("release_content_mutation=NONE")


if __name__ == "__main__":
    main()
