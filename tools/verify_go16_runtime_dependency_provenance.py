#!/usr/bin/env python3
"""GO-16 runtime dependency and container provenance verifier."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "evidence" / "governance" / "GO-16-RUNTIME-DEPENDENCY-POLICY.json"
WORKFLOW_DIR = ROOT / ".github" / "workflows"

IMAGE = re.compile(r"^\s*image:\s*['\"]?([^'\"#\s]+)", re.MULTILINE)
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
CARGO_RESOLVER = re.compile(
    r"^\s*(?:run:\s*)?cargo\s+(metadata|check|build|test|clippy|doc)\b(.*)$"
)
EXACT_NPM_PACKAGE = re.compile(r"^[A-Za-z0-9_.@/-]+@[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9_.-]+)?$")


def fail(errors: list[str]) -> None:
    print("GO-16 RUNTIME DEPENDENCY PROVENANCE: FAIL")
    for error in errors:
        print(f"ERROR: {error}")
    raise SystemExit(1)


def yaml_sources() -> list[Path]:
    files = [
        path
        for path in WORKFLOW_DIR.iterdir()
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


def package_projects() -> list[Path]:
    ignored = {"node_modules", ".runtime"}
    projects = []
    for path in ROOT.rglob("package.json"):
        if any(part in ignored for part in path.parts):
            continue
        projects.append(path)
    return sorted(projects)


def main() -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("schema") != "palaco.runtime-dependency-provenance.v1":
        fail(["unexpected policy schema"])

    errors: list[str] = []
    image_refs: list[tuple[str, str]] = []

    # 1. Container images used by CI/verification must be immutable digests.
    for path in yaml_sources():
        content = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for match in IMAGE.finditer(content):
            image = match.group(1)
            image_refs.append((rel, image))
            if not DIGEST.search(image):
                errors.append(f"{rel}: container image is not digest-pinned: {image}")

    expected_postgres = policy["container_policy"]["postgres_17_ci_image"]
    postgres_refs = [
        image for _, image in image_refs
        if image.startswith("postgres:17")
    ]
    if not postgres_refs:
        errors.append("no PostgreSQL 17 CI image reference found")
    for image in postgres_refs:
        if image != expected_postgres:
            errors.append(
                "PostgreSQL 17 CI image differs from evidenced digest: "
                f"{image}"
            )

    # 2. Cargo lockfile boundaries.
    if not (ROOT / "Cargo.lock").is_file():
        errors.append("root Cargo.lock is missing")

    for manifest, lockfile in policy["cargo_policy"]["standalone_manifests"].items():
        if not (ROOT / manifest).is_file():
            errors.append(f"standalone Cargo manifest missing: {manifest}")
        if not (ROOT / lockfile).is_file():
            errors.append(f"standalone Cargo lockfile missing: {lockfile}")

    cargo_commands = 0
    for path in sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml")):
        rel = path.relative_to(ROOT).as_posix()
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            match = CARGO_RESOLVER.match(line)
            if not match:
                continue
            cargo_commands += 1
            args = match.group(2)
            if "--version" in args:
                continue
            if "--locked" not in args:
                errors.append(
                    f"{rel}: dependency-resolving Cargo command lacks --locked: {line}"
                )

    # 3. npm projects with dependencies must carry package-lock.json.
    dependency_projects = 0
    for package_json in package_projects():
        data = json.loads(package_json.read_text(encoding="utf-8"))
        dependency_sections = [
            data.get("dependencies") or {},
            data.get("devDependencies") or {},
            data.get("optionalDependencies") or {},
        ]
        has_dependencies = any(bool(section) for section in dependency_sections)
        if not has_dependencies:
            continue
        dependency_projects += 1
        lock = package_json.with_name("package-lock.json")
        if not lock.is_file():
            errors.append(
                f"{package_json.relative_to(ROOT).as_posix()}: dependencies exist but package-lock.json is missing"
            )

    # 4. Direct npm install commands in workflows must use exact package versions.
    direct_npm_installs = 0
    npm_install = re.compile(r"\bnpm\s+install\b([^\n]*)")
    for path in sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml")):
        rel = path.relative_to(ROOT).as_posix()
        content = path.read_text(encoding="utf-8")
        for match in npm_install.finditer(content):
            direct_npm_installs += 1
            args = match.group(1).strip().split()
            package_args = [
                arg for arg in args
                if not arg.startswith("-")
                and not arg.startswith("$")
                and not arg.startswith('"$')
            ]
            if not package_args:
                errors.append(f"{rel}: direct npm install has no exact package argument")
                continue
            for package in package_args:
                package = package.strip('"\'')
                if not EXACT_NPM_PACKAGE.fullmatch(package):
                    errors.append(
                        f"{rel}: direct npm install package is not exact-version pinned: {package}"
                    )

    if errors:
        fail(errors)

    print("GO-16 RUNTIME DEPENDENCY PROVENANCE: PASS")
    print(f"container_image_refs={len(image_refs)}")
    print("container_images=SHA256_DIGEST_PINNED")
    print(f"cargo_dependency_commands={cargo_commands}")
    print("cargo_resolution=LOCKED")
    print(f"npm_dependency_projects={dependency_projects}")
    print("npm_dependency_projects=LOCKFILE_PRESENT")
    print(f"direct_npm_installs={direct_npm_installs}")
    print("direct_npm_install_versions=EXACT")
    print(f"postgres17_ci_image={expected_postgres}")


if __name__ == "__main__":
    main()
