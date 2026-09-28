#!/usr/bin/env python3
"""GO-10R licensing safety guard.

PASS means the unresolved licensing state is safely contained.
It does not mean a licensing model has been ratified.
"""

from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

root = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
package = root.get("workspace", {}).get("package", {})

if package.get("publish") is not False:
    errors.append("workspace publication is not fail-closed")

if package.get("license") != "Apache-2.0":
    errors.append("current assembly license declaration changed before ratification")

crates = [
    "palaco-foundation",
    "palaco-kernel",
    "palaco-runtime",
    "palaco-eventbus",
    "palaco-quay",
    "palaco-citadel",
    "palaco-evolution",
]
for crate in crates:
    data = tomllib.loads(
        (ROOT / "crates" / crate / "Cargo.toml").read_text(encoding="utf-8")
    )
    publish = data.get("package", {}).get("publish")
    if not isinstance(publish, dict) or publish.get("workspace") is not True:
        errors.append(f"{crate} does not inherit publish=false")

license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
if "License placeholder for repository assembly." not in license_text:
    errors.append("root LICENSE no longer carries the unresolved assembly marker")

pis011 = (ROOT / "docs" / "implementation" / "PIS" / "PIS-011.md").read_text(
    encoding="utf-8"
)
if 'license = "MIT OR Apache-2.0"' not in pis011:
    errors.append("PIS-011 dual-license evidence is missing")

dossier = ROOT / "evidence" / "audits" / "GO-10R-CANONICAL-LICENSE-RESOLUTION.md"
if not dossier.is_file():
    errors.append("GO-10R resolution dossier is missing")

unexpected = []
for name in ["LICENSE-MIT", "LICENSE-APACHE", "LICENCE", "COPYING", "NOTICE"]:
    if (ROOT / name).exists():
        unexpected.append(name)
if unexpected:
    errors.append(
        "license artifacts appeared before recorded owner ratification: "
        + ", ".join(unexpected)
    )

if errors:
    print("GO-10R SAFETY GUARD: FAIL")
    for item in errors:
        print(f"ERROR: {item}")
    sys.exit(1)

print("GO-10R SAFETY GUARD: PASS")
print("resolution_status=AWAITING_OWNER_RATIFICATION")
print("publication_guard=FAIL_CLOSED")
print("release_readiness=BLOCKED")
print("go11=LOCKED")
print("candidate_A=MIT OR Apache-2.0")
print("candidate_B=Apache-2.0")
print("license_decision=NOT_INFERRED")
