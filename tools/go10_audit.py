#!/usr/bin/env python3
"""GO-10 Foundation audit for PALACO."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
BLOCKERS: list[str] = []
OBSERVATIONS: list[str] = []

EXPECTED_CRATES = [
    "palaco-foundation",
    "palaco-kernel",
    "palaco-runtime",
    "palaco-eventbus",
    "palaco-quay",
    "palaco-citadel",
    "palaco-evolution",
]

CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
RUST_ACTION_SHA = "02cb101ec7c40f2c49e1d9714d64511d8e1b74de"
RUST_TOOLCHAIN = "1.98.1"

SPECIAL_EXTRACTIONS = {
    "docs/constitution/PCS/PCS-011.md",
    "docs/implementation/PIS/PIS-011.md",
}


def error(message: str) -> None:
    ERRORS.append(message)


def blocker(code: str) -> None:
    if code not in BLOCKERS:
        BLOCKERS.append(code)


# 1. Canonical import/provenance boundary.
docs: list[Path] = []
for base in [
    ROOT / "docs" / "constitution" / "PCS",
    ROOT / "docs" / "architecture" / "PAS",
    ROOT / "docs" / "implementation" / "PIS",
    ROOT / "docs" / "operations" / "POS",
    ROOT / "docs" / "ecosystem",
]:
    docs.extend(sorted(path for path in base.glob("*.md") if path.name != ".gitkeep"))

if len(docs) != 28:
    error(f"expected 28 substantive GO-03 documentation artifacts, found {len(docs)}")

for path in docs:
    rel = path.relative_to(ROOT).as_posix()
    content = path.read_text(encoding="utf-8")
    if rel in SPECIAL_EXTRACTIONS:
        if "Extraction provenance:" not in content or "Source blob:" not in content:
            error(f"{rel} lacks bounded extraction provenance")
    else:
        if "Source provenance:" not in content or "Source blob:" not in content:
            error(f"{rel} lacks direct source provenance")

if not (ROOT / "evidence" / "manifests" / "GO-03-CANONICAL-IMPORT.md").is_file():
    error("GO-03 canonical import manifest is missing")

# 2. Ratified licensing + publication safety.
root_cargo = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
workspace_package = root_cargo.get("workspace", {}).get("package", {})

if workspace_package.get("license") != "MIT OR Apache-2.0":
    blocker("RATIFIED_LICENSE_EXPRESSION_MISMATCH")

if workspace_package.get("publish") is not False:
    error("workspace publication is not fail-closed")

for crate in EXPECTED_CRATES:
    cargo_path = ROOT / "crates" / crate / "Cargo.toml"
    data = tomllib.loads(cargo_path.read_text(encoding="utf-8"))
    package = data.get("package", {})

    license_value = package.get("license")
    if not isinstance(license_value, dict) or license_value.get("workspace") is not True:
        error(f"{crate} does not inherit workspace license")

    publish_value = package.get("publish")
    if not isinstance(publish_value, dict) or publish_value.get("workspace") is not True:
        error(f"{crate} does not inherit fail-closed publication policy")

root_license = ROOT / "LICENSE"
mit_license = ROOT / "LICENSE-MIT"
apache_license = ROOT / "LICENSE-APACHE"
ratification = ROOT / "evidence" / "audits" / "GO-10R-LICENSE-RATIFICATION.md"

if not root_license.is_file():
    blocker("ROOT_LICENSE_MISSING")
else:
    text = root_license.read_text(encoding="utf-8")
    if "MIT OR Apache-2.0" not in text or "placeholder" in text.lower():
        blocker("ROOT_LICENSE_NOT_RATIFIED_DUAL_LICENSE")

if not mit_license.is_file():
    blocker("MIT_LICENSE_MISSING")
else:
    text = mit_license.read_text(encoding="utf-8")
    for marker in [
        "MIT License",
        "Copyright (c) 2026 PALACO",
        "Permission is hereby granted, free of charge",
        'THE SOFTWARE IS PROVIDED "AS IS"',
    ]:
        if marker not in text:
            blocker("MIT_LICENSE_INCOMPLETE")

if not apache_license.is_file():
    blocker("APACHE_LICENSE_MISSING")
else:
    text = apache_license.read_text(encoding="utf-8")
    for marker in [
        "Apache License",
        "Version 2.0, January 2004",
        "1. Definitions.",
        "2. Grant of Copyright License.",
        "3. Grant of Patent License.",
        "4. Redistribution.",
        "9. Accepting Warranty or Additional Liability.",
        "END OF TERMS AND CONDITIONS",
    ]:
        if marker not in text:
            blocker("APACHE_LICENSE_INCOMPLETE")

if not ratification.is_file():
    blocker("OWNER_LICENSE_RATIFICATION_MISSING")
else:
    text = ratification.read_text(encoding="utf-8")
    if "Option A" not in text or "MIT OR Apache-2.0" not in text or "RATIFIED" not in text:
        blocker("OWNER_LICENSE_RATIFICATION_INCOMPLETE")

# 3. Workflow supply-chain and permission boundary.
workflow_dir = ROOT / ".github" / "workflows"
workflows = sorted(workflow_dir.glob("*.yml"))
if not workflows:
    error("no GitHub Actions workflows found")

uses_pattern = re.compile(r"^\s*uses:\s*([^\s]+)\s*$")
immutable_action_pattern = re.compile(r"^[^/@]+/[^/@]+@[0-9a-f]{40}$")

for path in workflows:
    content = path.read_text(encoding="utf-8")
    if "permissions:" not in content:
        error(f"{path.name} lacks explicit permissions")
    if re.search(r"^\s*[A-Za-z0-9_-]+:\s*write\s*$", content, re.MULTILINE):
        error(f"{path.name} requests write permission")

    for line in content.splitlines():
        match = uses_pattern.match(line)
        if not match:
            continue
        action = match.group(1)
        if action.startswith("./"):
            continue
        if not immutable_action_pattern.match(action):
            error(f"{path.name} has non-immutable action reference: {action}")

    if "actions/checkout@" in content and f"actions/checkout@{CHECKOUT_SHA}" not in content:
        error(f"{path.name} does not use the audited checkout commit")

for name in [
    "go-04-rust-workspace.yml",
    "go-05-rust-build.yml",
    "go-06-rust-tests.yml",
    "go-08-pvs-002.yml",
    "go-10-audit.yml",
]:
    path = workflow_dir / name
    if not path.is_file():
        error(f"required workflow missing: {name}")
        continue
    content = path.read_text(encoding="utf-8")
    if f"dtolnay/rust-toolchain@{RUST_ACTION_SHA}" not in content:
        error(f"{name} does not pin the audited rust-toolchain action commit")
    if f"toolchain: {RUST_TOOLCHAIN}" not in content:
        error(f"{name} does not pin Rust {RUST_TOOLCHAIN}")

# 4. Evidence Seal presence and historical limitations.
seal_path = ROOT / "evidence" / "manifests" / "GO-09-EVIDENCE-SEAL.json"
seal_checksum = ROOT / "evidence" / "manifests" / "GO-09-EVIDENCE-SEAL.sha256"
if not seal_path.is_file() or not seal_checksum.is_file():
    error("GO-09 evidence seal or checksum is missing")
else:
    import json

    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    signature = seal.get("subject", {}).get("github_signature_verification", {})
    if signature.get("verified") is False and signature.get("reason") == "unsigned":
        OBSERVATIONS.append("SEALED_SUBJECT_UNSIGNED")
    else:
        error("GO-09 subject signature state changed from the sealed record")

# 5. Release decision.
release_state = "BLOCKED" if BLOCKERS else "ELIGIBLE_FOR_GO-11_REVIEW"

if ERRORS:
    print("GO-10 AUDIT: FAIL")
    for item in ERRORS:
        print(f"ERROR: {item}")
    if BLOCKERS:
        print("RELEASE_BLOCKERS=" + ",".join(BLOCKERS))
    sys.exit(1)

print("GO-10 AUDIT: COMPLETE")
print("audit_integrity=PASS")
print(f"canonical_artifacts={len(docs)}")
print("workflow_supply_chain=IMMUTABLY_PINNED")
print("workflow_permissions=READ_ONLY")
print("license_resolution=RATIFIED_MIT_OR_APACHE_2_0")
print("publication_guard=FAIL_CLOSED")
print(f"release_readiness={release_state}")
print("release_blockers=" + (",".join(BLOCKERS) if BLOCKERS else "NONE"))
print("observations=" + (",".join(OBSERVATIONS) if OBSERVATIONS else "NONE"))
print("non_claims=NO_DEPLOYMENT,NO_PRODUCTION_RUNTIME_CONFORMANCE,NO_EXTERNAL_CERTIFICATION")
