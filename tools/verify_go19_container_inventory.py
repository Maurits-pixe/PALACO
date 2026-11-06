#!/usr/bin/env python3
"""GO-19 container inventory and coverage verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "evidence" / "governance" / "GO-19-CONTAINER-VULNERABILITY-POLICY.json"
EXCEPTIONS = ROOT / "evidence" / "governance" / "GO-19-CONTAINER-VULNERABILITY-EXCEPTIONS.json"
WORKFLOWS = ROOT / ".github" / "workflows"

IMAGE = re.compile(r"^\s*image:\s*['\"]?([^'\"#\s]+)", re.MULTILINE)
DIGEST = re.compile(r"@sha256:([0-9a-f]{64})$")


def fail(errors: list[str]) -> None:
    print("GO-19 CONTAINER INVENTORY: FAIL")
    for error in errors:
        print(f"ERROR: {error}")
    raise SystemExit(1)


def yaml_sources() -> list[Path]:
    files = [
        path
        for path in WORKFLOWS.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    ]
    verification = ROOT / "verification"
    if verification.is_dir():
        files.extend(
            path
            for path in verification.rglob("*")
            if path.is_file()
            and path.suffix in {".yml", ".yaml"}
            and ("compose" in path.name.lower() or "docker" in path.name.lower())
        )
    return sorted(set(files))


def detected_images() -> list[str]:
    refs: set[str] = set()
    for path in yaml_sources():
        content = path.read_text(encoding="utf-8")
        refs.update(IMAGE.findall(content))
    return sorted(refs)


def matrix_entry(image: str) -> dict[str, str]:
    match = DIGEST.search(image)
    if not match:
        digest_id = hashlib.sha256(image.encode()).hexdigest()[:16]
    else:
        digest_id = match.group(1)[:16]
    return {"id": digest_id, "image": image}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", action="store_true")
    args = parser.parse_args()

    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    exceptions = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))

    errors: list[str] = []
    if policy.get("schema") != "palaco.container-vulnerability-policy.v1":
        errors.append("unexpected GO-19 policy schema")

    images = detected_images()
    expected = sorted(policy.get("images", []))

    if not images:
        errors.append("no container images detected")
    if images != expected:
        errors.append(
            "container coverage mismatch; detected="
            + json.dumps(images)
            + " policy="
            + json.dumps(expected)
        )

    for image in images:
        if DIGEST.search(image) is None:
            errors.append(f"container image is not sha256 digest pinned: {image}")

    scanner = policy.get("scanner", {})
    if scanner.get("action") != "aquasecurity/trivy-action":
        errors.append("unexpected scanner action")
    action_sha = str(scanner.get("action_sha", ""))
    if re.fullmatch(r"[0-9a-f]{40}", action_sha) is None:
        errors.append("scanner action is not pinned to a 40-hex commit")
    if re.fullmatch(r"v\d+\.\d+\.\d+", str(scanner.get("trivy_version", ""))) is None:
        errors.append("Trivy binary version is not an exact release version")

    blocking = set(policy.get("blocking_severities", []))
    if blocking != {"CRITICAL", "HIGH", "UNKNOWN"}:
        errors.append("blocking severity policy drifted from CRITICAL,HIGH,UNKNOWN")

    if exceptions.get("schema") != "palaco.container-vulnerability-exceptions.v1":
        errors.append("unexpected GO-19 exception schema")
    raw_exceptions = exceptions.get("exceptions", [])
    if not isinstance(raw_exceptions, list):
        errors.append("GO-19 exceptions must be a list")
        raw_exceptions = []

    seen: set[tuple[str, str, str, str]] = set()
    for item in raw_exceptions:
        key = (
            str(item.get("vulnerability_id", "")),
            str(item.get("image", "")),
            str(item.get("package", "")),
            str(item.get("installed_version", "")),
        )
        if not all(key):
            errors.append(f"incomplete exception identity: {key}")
            continue
        if key in seen:
            errors.append(f"duplicate exception identity: {key}")
        seen.add(key)
        if key[1] not in expected:
            errors.append(f"exception references image outside policy: {key[1]}")

    if errors:
        fail(errors)

    matrix = [matrix_entry(image) for image in images]
    if args.matrix:
        print(json.dumps(matrix, separators=(",", ":")))
        return

    print("GO-19 CONTAINER INVENTORY: PASS")
    print(f"container_images={len(images)}")
    print("container_coverage=COMPLETE")
    print("container_identity=SHA256_DIGEST_PINNED")
    print(f"scanner_action_sha={action_sha}")
    print(f"trivy_version={scanner['trivy_version']}")
    print("blocking_severities=CRITICAL,HIGH,UNKNOWN")
    print(f"exceptions={len(raw_exceptions)}")


if __name__ == "__main__":
    main()
