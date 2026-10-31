#!/usr/bin/env python3
"""GO-15 repository-wide GitHub Actions supply-chain verifier."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
POLICY_PATH = ROOT / "evidence" / "governance" / "GO-15-WORKFLOW-SUPPLY-CHAIN-POLICY.json"

IMMUTABLE_ACTION = re.compile(r"^[^/@]+/[^/@]+@[0-9a-f]{40}$")
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")
TOP_LEVEL_PERMISSIONS = re.compile(r"^permissions:\s*$", re.MULTILINE)
WRITE_SCOPE = re.compile(r"^\s{2}([A-Za-z0-9_-]+):\s*write\s*$", re.MULTILINE)


def fail(errors: list[str]) -> None:
    print("GO-15 WORKFLOW SUPPLY CHAIN: FAIL")
    for item in errors:
        print(f"ERROR: {item}")
    raise SystemExit(1)


def main() -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("schema") != "palaco.workflow-supply-chain.v1":
        fail(["unexpected policy schema"])

    exceptions = {
        path: set(scopes)
        for path, scopes in policy.get("write_exceptions", {}).items()
    }

    workflows = sorted(
        path for path in WORKFLOW_DIR.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    )

    errors: list[str] = []
    action_refs = 0
    exception_hits: set[str] = set()

    for path in workflows:
        rel = path.relative_to(ROOT).as_posix()
        content = path.read_text(encoding="utf-8")

        if "permissions: write-all" in content:
            errors.append(f"{rel}: permissions: write-all is forbidden")

        if not TOP_LEVEL_PERMISSIONS.search(content):
            errors.append(f"{rel}: explicit top-level permissions block missing")

        writes = set(WRITE_SCOPE.findall(content))
        allowed_writes = exceptions.get(rel, set())

        if writes != allowed_writes:
            if writes and not allowed_writes:
                errors.append(
                    f"{rel}: write permissions {sorted(writes)} are not approved"
                )
            elif allowed_writes and writes != allowed_writes:
                errors.append(
                    f"{rel}: write permissions mismatch; expected "
                    f"{sorted(allowed_writes)}, got {sorted(writes)}"
                )

        if rel in exceptions and writes == allowed_writes:
            exception_hits.add(rel)

        for line in content.splitlines():
            match = USES.match(line)
            if not match:
                continue
            action = match.group(1)
            if action.startswith("./"):
                continue
            action_refs += 1
            if not IMMUTABLE_ACTION.fullmatch(action):
                errors.append(f"{rel}: mutable external action reference: {action}")

    stale_exceptions = set(exceptions) - exception_hits
    for rel in sorted(stale_exceptions):
        errors.append(f"{rel}: write exception is stale or not exactly exercised")

    if errors:
        fail(errors)

    print("GO-15 WORKFLOW SUPPLY CHAIN: PASS")
    print(f"workflow_count={len(workflows)}")
    print(f"external_action_refs={action_refs}")
    print("external_actions=IMMUTABLE_COMMIT_SHA_ONLY")
    print("permissions=EXPLICIT")
    print("write_default=DENY")
    print(
        "write_exceptions="
        + (",".join(sorted(exceptions)) if exceptions else "NONE")
    )


if __name__ == "__main__":
    main()
