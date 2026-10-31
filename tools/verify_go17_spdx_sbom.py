#!/usr/bin/env python3
"""Verify GO-17 generated SPDX dependency inventory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SBOM = ROOT / "artifacts" / "go17" / "PALACO.spdx.json"


def fail(message: str) -> None:
    print(f"GO-17 SPDX VERIFY: FAIL - {message}")
    raise SystemExit(1)


def main() -> None:
    if not SBOM.is_file():
        fail("generated SBOM is missing")
    raw = SBOM.read_bytes()
    data = json.loads(raw)

    required = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
    }
    for key, expected in required.items():
        if data.get(key) != expected:
            fail(f"{key} mismatch: expected {expected!r}, got {data.get(key)!r}")

    packages = data.get("packages")
    if not isinstance(packages, list) or not packages:
        fail("SBOM contains no packages")

    ids = [p.get("SPDXID") for p in packages]
    if any(not isinstance(value, str) for value in ids):
        fail("package without SPDXID")
    if len(ids) != len(set(ids)):
        fail("duplicate package SPDXIDs")

    described = data.get("documentDescribes", [])
    if set(described) != set(ids):
        fail("documentDescribes does not exactly match package inventory")

    for package in packages:
        if not package.get("name") or not package.get("versionInfo"):
            fail("package missing name/versionInfo")
        if package.get("filesAnalyzed") is not False:
            fail("derived dependency package must use filesAnalyzed=false")
        if package.get("licenseConcluded") != "NOASSERTION":
            fail("generator must not invent license conclusions")

        if package.get("primaryPackagePurpose") == "CONTAINER":
            checksums = package.get("checksums", [])
            if len(checksums) != 1 or checksums[0].get("algorithm") != "SHA256":
                fail("container package missing SHA256 checksum")
            if not re.fullmatch(r"[0-9a-f]{64}", checksums[0].get("checksumValue", "")):
                fail("container package has malformed SHA256")

    relationships = data.get("relationships", [])
    described_by_relationship = {
        item.get("relatedSpdxElement")
        for item in relationships
        if item.get("spdxElementId") == "SPDXRef-DOCUMENT"
        and item.get("relationshipType") == "DESCRIBES"
    }
    if described_by_relationship != set(ids):
        fail("DESCRIBES relationships do not exactly match package inventory")

    digest = hashlib.sha256(raw).hexdigest()
    print("GO-17 SPDX VERIFY: PASS")
    print(f"packages_total={len(packages)}")
    print(f"sbom_sha256={digest}")
    print("license_conclusions=NOASSERTION_PRESERVED")
    print("container_digests=SHA256_PRESENT")


if __name__ == "__main__":
    main()
