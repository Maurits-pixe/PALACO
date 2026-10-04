#!/usr/bin/env python3
"""PVS-001 workspace integrity verification for PALACO Foundation Edition v1.0.0."""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = [
    "palaco-foundation",
    "palaco-kernel",
    "palaco-runtime",
    "palaco-eventbus",
    "palaco-quay",
    "palaco-citadel",
    "palaco-evolution",
]

errors = []
root_cargo = (ROOT / "Cargo.toml").read_text(encoding="utf-8")

for token in ('version = "1.0.0"', 'edition = "2024"', 'unsafe_code = "forbid"', 'unwrap_used = "deny"', 'todo = "deny"'):
    if token not in root_cargo:
        errors.append(f"root Cargo.toml missing invariant: {token}")

members = re.findall(r'"crates/([^"]+)"', root_cargo)
if members != EXPECTED:
    errors.append(f"workspace members mismatch: {members!r}")

for name in EXPECTED:
    crate = ROOT / "crates" / name
    cargo = crate / "Cargo.toml"
    lib = crate / "src" / "lib.rs"
    if not cargo.is_file():
        errors.append(f"missing {cargo.relative_to(ROOT)}")
        continue
    if not lib.is_file():
        errors.append(f"missing {lib.relative_to(ROOT)}")
    text = cargo.read_text(encoding="utf-8")
    required = [
        f'name = "{name}"',
        "version.workspace = true",
        "edition.workspace = true",
        "license.workspace = true",
        "[lints]",
        "workspace = true",
    ]
    for token in required:
        if token not in text:
            errors.append(f"{cargo.relative_to(ROOT)} missing: {token}")

required_dirs = [
    "docs/constitution/PCS",
    "docs/architecture/PAS",
    "docs/implementation/PIS",
    "docs/operations/POS",
    "docs/ecosystem",
    "tests/integration",
    "tests/constitutional",
    "tests/provenance",
    "tests/replay",
    "evidence/pvs",
    "evidence/audits",
    "evidence/manifests",
    "tools",
    ".github/workflows",
    ".github/ISSUE_TEMPLATE",
    ".github/PULL_REQUEST_TEMPLATE",
]
for rel in required_dirs:
    if not (ROOT / rel).is_dir():
        errors.append(f"missing required directory: {rel}")

if errors:
    print("PVS-001: FAIL")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("PVS-001: PASS")
print("Foundation workspace identity, membership, lints, crates, and required repository boundaries are structurally consistent.")
