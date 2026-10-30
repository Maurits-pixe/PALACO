#!/usr/bin/env python3
"""Generate a deterministic SPDX 2.3 dependency inventory for PALACO.

Sources:
- Cargo.lock packages
- npm package-lock.json dependency packages
- digest-pinned container images referenced by GitHub Actions workflows

The document is derived evidence. It does not assert vulnerability freedom,
license conclusions, runtime safety, or constitutional authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "go17" / "PALACO.spdx.json"


def fail(message: str) -> None:
    print(f"GO-17 SBOM: FAIL - {message}")
    raise SystemExit(1)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        fail(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def spdx_id(kind: str, identity: str) -> str:
    digest = hashlib.sha256(f"{kind}:{identity}".encode()).hexdigest()[:20]
    return f"SPDXRef-{kind}-{digest}"


def utc_commit_time() -> str:
    iso = git("show", "-s", "--format=%cI", "HEAD")
    value = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def cargo_packages() -> list[dict]:
    lock = ROOT / "Cargo.lock"
    if not lock.is_file():
        fail("Cargo.lock is missing")

    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    out = []
    for package in data.get("package", []):
        name = package.get("name")
        version = package.get("version")
        if not name or not version:
            fail("Cargo.lock contains a package without name/version")
        source = package.get("source", "workspace")
        identity = f"cargo:{name}@{version}:{source}"
        entry = {
            "SPDXID": spdx_id("Cargo", identity),
            "name": name,
            "versionInfo": str(version),
            "downloadLocation": source if isinstance(source, str) and source.startswith("git+") else "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "supplier": "NOASSERTION",
            "originator": "NOASSERTION",
            "primaryPackagePurpose": "LIBRARY",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:cargo/{name}@{version}",
                }
            ],
            "annotations": [
                {
                    "annotationDate": "1970-01-01T00:00:00Z",
                    "annotationType": "OTHER",
                    "annotator": "Tool: PALACO GO-17",
                    "comment": f"source={source}",
                }
            ],
        }
        checksum = package.get("checksum")
        if checksum:
            entry["checksums"] = [{"algorithm": "SHA256", "checksumValue": checksum}]
        out.append(entry)
    return out


def npm_packages() -> list[dict]:
    out = []
    for lock in sorted(ROOT.rglob("package-lock.json")):
        if any(part in {"node_modules", "target", ".git"} for part in lock.parts):
            continue
        data = json.loads(lock.read_text(encoding="utf-8"))
        packages = data.get("packages", {})
        for rel_path, package in sorted(packages.items()):
            if rel_path == "":
                continue
            name = package.get("name")
            if not name:
                marker = "node_modules/"
                if marker in rel_path:
                    name = rel_path.split(marker, 1)[1]
            version = package.get("version")
            if not name or not version:
                continue
            identity = f"npm:{lock.relative_to(ROOT)}:{name}@{version}:{rel_path}"
            out.append(
                {
                    "SPDXID": spdx_id("Npm", identity),
                    "name": name,
                    "versionInfo": str(version),
                    "downloadLocation": package.get("resolved", "NOASSERTION"),
                    "filesAnalyzed": False,
                    "licenseConcluded": "NOASSERTION",
                    "licenseDeclared": "NOASSERTION",
                    "copyrightText": "NOASSERTION",
                    "supplier": "NOASSERTION",
                    "originator": "NOASSERTION",
                    "primaryPackagePurpose": "LIBRARY",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": f"pkg:npm/{name}@{version}",
                        }
                    ],
                    "annotations": [
                        {
                            "annotationDate": "1970-01-01T00:00:00Z",
                            "annotationType": "OTHER",
                            "annotator": "Tool: PALACO GO-17",
                            "comment": f"lockfile={lock.relative_to(ROOT).as_posix()} path={rel_path}",
                        }
                    ],
                }
            )
    return out


IMAGE_RE = re.compile(r"^\s*image:\s*([^\s#]+)", re.MULTILINE)


def container_packages() -> list[dict]:
    refs: set[str] = set()
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        refs.update(IMAGE_RE.findall(workflow.read_text(encoding="utf-8")))
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yaml")):
        refs.update(IMAGE_RE.findall(workflow.read_text(encoding="utf-8")))

    out = []
    for ref in sorted(refs):
        if "@sha256:" not in ref:
            fail(f"container image is not digest pinned: {ref}")
        image_name, digest = ref.split("@sha256:", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail(f"container image has malformed sha256 digest: {ref}")
        identity = f"container:{image_name}@sha256:{digest}"
        out.append(
            {
                "SPDXID": spdx_id("Container", identity),
                "name": image_name,
                "versionInfo": f"sha256:{digest}",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "supplier": "NOASSERTION",
                "originator": "NOASSERTION",
                "primaryPackagePurpose": "CONTAINER",
                "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
                "annotations": [
                    {
                        "annotationDate": "1970-01-01T00:00:00Z",
                        "annotationType": "OTHER",
                        "annotator": "Tool: PALACO GO-17",
                        "comment": f"image_ref={ref}",
                    }
                ],
            }
        )
    return out


def main() -> None:
    commit = git("rev-parse", "HEAD")
    packages = cargo_packages() + npm_packages() + container_packages()
    packages.sort(key=lambda item: (item["name"], item.get("versionInfo", ""), item["SPDXID"]))

    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": package["SPDXID"],
        }
        for package in packages
    ]

    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "PALACO dependency inventory",
        "documentNamespace": f"https://palaco.invalid/spdx/go-17/{commit}",
        "creationInfo": {
            "created": utc_commit_time(),
            "creators": ["Tool: PALACO GO-17 deterministic SBOM generator"],
        },
        "documentDescribes": [p["SPDXID"] for p in packages],
        "packages": packages,
        "relationships": relationships,
        "annotations": [
            {
                "annotationDate": utc_commit_time(),
                "annotationType": "OTHER",
                "annotator": "Tool: PALACO GO-17",
                "comment": (
                    "Derived from committed lockfiles and digest-pinned CI container references. "
                    "NOASSERTION is retained where authoritative license/supplier data is not proven."
                ),
            }
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
    OUT.write_bytes(encoded)

    digest = hashlib.sha256(encoded).hexdigest()
    cargo_count = sum(1 for p in packages if p["SPDXID"].startswith("SPDXRef-Cargo-"))
    npm_count = sum(1 for p in packages if p["SPDXID"].startswith("SPDXRef-Npm-"))
    container_count = sum(1 for p in packages if p["SPDXID"].startswith("SPDXRef-Container-"))

    print("GO-17 SBOM: GENERATED")
    print(f"commit={commit}")
    print(f"packages_total={len(packages)}")
    print(f"cargo_packages={cargo_count}")
    print(f"npm_packages={npm_count}")
    print(f"container_packages={container_count}")
    print(f"sbom_sha256={digest}")
    print(f"output={OUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
