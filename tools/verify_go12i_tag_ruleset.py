#!/usr/bin/env python3
"""GO-12I server-side immutability verifier for PALACO v1.0.0."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DESIRED = ROOT / "evidence" / "governance" / "GO-12I-V1.0.0-TAG-RULESET.json"


def fail(message: str) -> None:
    print(f"GO-12I TAG RULESET: FAIL - {message}")
    raise SystemExit(1)


def github_json(url: str):
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PALACO-GO-12I-Tag-Ruleset",
        "X-GitHub-Api-Version": "2026-03-10",
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


def normalized_rules(rules):
    return {rule.get("type") for rule in rules if isinstance(rule, dict)}


def main() -> None:
    desired = json.loads(DESIRED.read_text(encoding="utf-8"))

    if desired.get("target") != "tag":
        fail("desired ruleset target is not tag")
    if desired.get("enforcement") != "active":
        fail("desired ruleset enforcement is not active")
    if desired.get("bypass_actors") != []:
        fail("desired ruleset must not define bypass actors")

    desired_refs = set(desired["conditions"]["ref_name"]["include"])
    if desired_refs != {"refs/tags/v1.0.0"}:
        fail("desired ruleset must target only refs/tags/v1.0.0")

    required_rules = {"update", "deletion"}
    if not required_rules.issubset(normalized_rules(desired["rules"])):
        fail("desired ruleset lacks update/deletion protection")

    rulesets = github_json("https://api.github.com/repos/Maurits-pixe/PALACO/rulesets")
    candidates = [
        item for item in rulesets
        if item.get("target") == "tag" and item.get("enforcement") == "active"
    ]

    matched = None
    for item in candidates:
        detail = github_json(
            f"https://api.github.com/repos/Maurits-pixe/PALACO/rulesets/{item['id']}"
        )
        refs = set(detail.get("conditions", {}).get("ref_name", {}).get("include", []))
        rules = normalized_rules(detail.get("rules", []))
        bypass = detail.get("bypass_actors", [])
        if (
            "refs/tags/v1.0.0" in refs
            and required_rules.issubset(rules)
            and not bypass
        ):
            matched = detail
            break

    if matched is None:
        print("GO-12I TAG RULESET: BLOCKED")
        print("required_target=refs/tags/v1.0.0")
        print("required_rules=update,deletion")
        print("required_enforcement=active")
        print("required_bypass_actors=NONE")
        print("server_side_prevention=ABSENT")
        raise SystemExit(1)

    print("GO-12I TAG RULESET: PASS")
    print(f"ruleset_id={matched['id']}")
    print(f"ruleset_name={matched['name']}")
    print("target=refs/tags/v1.0.0")
    print("rules=update,deletion")
    print("enforcement=active")
    print("bypass_actors=NONE")
    print("server_side_prevention=ENFORCED")


if __name__ == "__main__":
    main()
