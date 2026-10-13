#!/usr/bin/env python3
"""Emit only explicitly allowlisted public source/build evidence for remote authoring."""
import base64
import hashlib
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SOURCES = (
    "services/rio-accounts/Cargo.lock",
    "services/rio-accounts/src/lib.rs",
    "services/rio-accounts/src/main.rs",
    "services/rio-accounts/src/storage.rs",
    "verification/rio-accounts/package-lock.json",
)
if len(sys.argv) != 2 or sys.argv[1] not in ("sources", "summary", "inputs"):
    raise SystemExit("Unsupported public evidence operation")
if sys.argv[1] == "sources":
    for name in SOURCES:
        path = REPO / name
        if path.is_file() and not path.is_symlink():
            value = base64.b64encode(path.read_bytes()).decode("ascii")
            print("RIO_PUBLIC_SOURCE_BEGIN " + name)
            print(value)
            print("RIO_PUBLIC_SOURCE_END")
elif sys.argv[1] == "summary":
    path = REPO / "verification/rio-accounts/evidence/browser-summary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    print("RIO_BROWSER_SUMMARY " + json.dumps(data, separators=(",", ":")))
else:
    result = subprocess.run(
        ["docker", "image", "inspect", "quay.io/keycloak/keycloak:26.8.0@sha256:27b3230fbabb8c9ff3c66c864cf09dcd8a41aca82e5100679d109ef0eeb05741",
         "--format", "{{index .RepoDigests 0}}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if not result.startswith("quay.io/keycloak/keycloak@sha256:"):
        raise SystemExit("Unrecognized development image digest")
    postgres = subprocess.run(
        ["docker", "image", "inspect", "postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c",
         "--format", "{{index .RepoDigests 0}}"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if not postgres.startswith("postgres@sha256:"):
        raise SystemExit("Unrecognized synthetic PostgreSQL image digest")
    data = {"schema": "rio-account-dev-build-inputs/v2", "keycloak": result, "postgres": postgres}
    for name in ("services/rio-accounts/Cargo.lock", "verification/rio-accounts/package-lock.json"):
        data[name] = hashlib.sha256((REPO / name).read_bytes()).hexdigest()
    print("RIO_BUILD_INPUTS " + json.dumps(data, separators=(",", ":")))
