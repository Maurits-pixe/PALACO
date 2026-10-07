#!/usr/bin/env python3
"""PVS-003 repository provenance and consolidation-boundary candidate."""

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MAIN_TREE = "96864384022191e7e6f6fd59134defbd3ae41151"
CLASSIFICATION = ROOT / "verification/GO-19B-FORENSIC-CLASSIFICATION.md"
PROTECTED = [
    "333333",
    "Canonical Status",
    "MBvanGeen/palaco-foundation",
    "PALACO_Foundation_v0.3.0_alpha.zip",
    "ALPHA",
]
EXPECTED_WORKSPACE = {
    "palaco-foundation",
    "palaco-kernel",
    "palaco-runtime",
    "palaco-eventbus",
    "palaco-quay",
    "palaco-citadel",
    "palaco-evolution",
}

errors = []

def git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"git {' '.join(args)} failed: {exc}")
        return ""

main_tree = git("rev-parse", "main^{tree}")
if main_tree and main_tree != EXPECTED_MAIN_TREE:
    errors.append(
        f"frozen main tree mismatch: expected {EXPECTED_MAIN_TREE}, got {main_tree}"
    )

for rel in PROTECTED:
    if not (ROOT / rel).exists():
        errors.append(f"protected historical path missing: {rel}")

if not CLASSIFICATION.is_file():
    errors.append("missing GO-19B forensic classification record")
else:
    text = CLASSIFICATION.read_text(encoding="utf-8")
    for marker in ("ACTIVE", "GOVERNANCE-EVIDENCE", "HISTORICAL-PRESERVE", "REVIEW-REQUIRED"):
        if marker not in text:
            errors.append(f"classification record missing category: {marker}")
    if "VORM9EVING" not in text:
        errors.append("classification record missing exact canonical identifier: VORM9EVING")

cargo = ROOT / "Cargo.toml"
if not cargo.is_file():
    errors.append("missing root Cargo.toml")
else:
    cargo_text = cargo.read_text(encoding="utf-8")
    members = set(re.findall(r'"crates/([^"]+)"', cargo_text))
    missing = sorted(EXPECTED_WORKSPACE - members)
    if missing:
        errors.append(f"expected Foundation workspace members missing: {missing}")

if errors:
    print("PVS-003: FAIL")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("PVS-003: PASS")
print("Frozen repository baseline, protected historical material, classification boundary, workspace membership, and exact canonical identifier are preserved.")
print("PVS-003 PASS != merge authority != canonical ascension")
