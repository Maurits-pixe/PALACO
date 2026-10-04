#!/usr/bin/env python3
"""GO-10R ratified dual-license verifier."""

from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

root = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
package = root.get("workspace", {}).get("package", {})

if package.get("license") != "MIT OR Apache-2.0":
    errors.append("workspace license expression is not the ratified dual license")

if package.get("publish") is not False:
    errors.append("workspace publication guard is not fail-closed")

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
    cargo_path = ROOT / "crates" / crate / "Cargo.toml"
    data = tomllib.loads(cargo_path.read_text(encoding="utf-8"))
    package_data = data.get("package", {})

    license_value = package_data.get("license")
    if not isinstance(license_value, dict) or license_value.get("workspace") is not True:
        errors.append(f"{crate} does not inherit the workspace license")

    publish_value = package_data.get("publish")
    if not isinstance(publish_value, dict) or publish_value.get("workspace") is not True:
        errors.append(f"{crate} does not inherit publish=false")

root_license = (ROOT / "LICENSE").read_text(encoding="utf-8")
if "MIT OR Apache-2.0" not in root_license:
    errors.append("root LICENSE does not declare the ratified dual license")
if "placeholder" in root_license.lower():
    errors.append("root LICENSE still contains placeholder language")

mit_path = ROOT / "LICENSE-MIT"
apache_path = ROOT / "LICENSE-APACHE"
if not mit_path.is_file():
    errors.append("LICENSE-MIT is missing")
else:
    mit = mit_path.read_text(encoding="utf-8")
    required_mit = [
        "MIT License",
        "Copyright (c) 2026 PALACO",
        "Permission is hereby granted, free of charge",
        'THE SOFTWARE IS PROVIDED "AS IS"',
    ]
    for marker in required_mit:
        if marker not in mit:
            errors.append(f"LICENSE-MIT missing marker: {marker}")

if not apache_path.is_file():
    errors.append("LICENSE-APACHE is missing")
else:
    apache = apache_path.read_text(encoding="utf-8")
    required_apache = [
        "Apache License",
        "Version 2.0, January 2004",
        "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
        "1. Definitions.",
        "2. Grant of Copyright License.",
        "3. Grant of Patent License.",
        "4. Redistribution.",
        "5. Submission of Contributions.",
        "6. Trademarks.",
        "7. Disclaimer of Warranty.",
        "8. Limitation of Liability.",
        "9. Accepting Warranty or Additional Liability.",
        "END OF TERMS AND CONDITIONS",
    ]
    for marker in required_apache:
        if marker not in apache:
            errors.append(f"LICENSE-APACHE missing marker: {marker}")

ratification = ROOT / "evidence" / "audits" / "GO-10R-LICENSE-RATIFICATION.md"
if not ratification.is_file():
    errors.append("GO-10R ratification record is missing")
else:
    text = ratification.read_text(encoding="utf-8")
    if "Option A" not in text or "MIT OR Apache-2.0" not in text or "RATIFIED" not in text:
        errors.append("GO-10R ratification record is incomplete")

pis011 = (ROOT / "docs" / "implementation" / "PIS" / "PIS-011.md").read_text(
    encoding="utf-8"
)
if 'license = "MIT OR Apache-2.0"' not in pis011:
    errors.append("PIS-011 corroborating dual-license declaration is missing")

if errors:
    print("GO-10R LICENSE RATIFICATION: FAIL")
    for item in errors:
        print(f"ERROR: {item}")
    sys.exit(1)

print("GO-10R LICENSE RATIFICATION: PASS")
print("resolution_status=RATIFIED")
print("license_expression=MIT OR Apache-2.0")
print("license_files=LICENSE,LICENSE-MIT,LICENSE-APACHE")
print("publication_guard=FAIL_CLOSED")
print("release_license_blocker=CLOSED")
print("license_decision=OWNER_RATIFIED_OPTION_A")
