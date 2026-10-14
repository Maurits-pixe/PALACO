"""Offline staging-plan checks. No network probes, runtime startup or account authority.

A consistent proposal is not a deployment configuration for rio-accounts-dev.
Only fixed result categories are emitted; input values and paths are never echoed.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
from typing import Any
from urllib.parse import urlsplit

LIMIT = 16_384
ENDPOINT_PATHS = {
    "bffOrigin": "",
    "idpIssuer": "/realms/rio-synthetic-staging",
    "callbackUrl": "/auth/callback",
    "discoveryUrl": "/realms/rio-synthetic-staging/.well-known/openid-configuration",
    "authorizationUrl": "/realms/rio-synthetic-staging/protocol/openid-connect/auth",
    "tokenUrl": "/realms/rio-synthetic-staging/protocol/openid-connect/token",
    "jwksUrl": "/realms/rio-synthetic-staging/protocol/openid-connect/certs",
}
FIXED = {
    "schemaVersion": "RIO_STAGING_PLAN_V1",
    "mode": "PLAN_ONLY",
    "oidc": {
        "clientId": "rio-bff-staging",
        "flow": "authorization_code",
        "pkce": "S256",
        "scope": ["openid"],
        "clientType": "CONFIDENTIAL",
        "registration": False,
        "directAccessGrants": False,
        "serviceAccounts": False,
    },
    "data": {
        "actors": ["TST-alpha", "TST-beta"],
        "personalData": False,
        "smtp": False,
    },
    "transport": {
        "browserTls": "TRUSTED_CERT_REQUIRED",
        "providerTls": "VERIFY_REQUIRED",
        "databaseTls": "VERIFY_FULL_REQUIRED",
        "forwardedHeaders": "REJECT_UNTIL_SEPARATELY_REVIEWED",
        "secretPolicy": "VALUES_FORBIDDEN_IN_PLAN",
    },
    "boundary": {
        "account1": "HOLD",
        "personalAccounts": False,
        "contact": False,
        "operativeAuthority": "NONE",
        "deployment": "HOLD",
    },
}
SOURCE_KEYS = {"repository", "commit"}
ARTIFACT_PATTERNS = {
    "idpImage": re.compile(r"quay\.io/keycloak/keycloak:[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}"),
    "databaseImage": re.compile(r"postgres:[0-9]+\.[0-9]+-bookworm@sha256:[0-9a-f]{64}"),
}
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
DNS_HOST = re.compile(rf"{LABEL}(?:\.{LABEL})+")
COMMIT = re.compile(r"[0-9a-f]{40}")


def _same(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return value.keys() == expected.keys() and all(
            _same(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _same(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def _keys(value: Any, required: set[str]) -> bool:
    return type(value) is dict and value.keys() == required


def _host(value: Any, path: str) -> str | None:
    # urlsplit normalizes some controls; reject them before parsing.
    if type(value) is not str or not 1 <= len(value) <= 512:
        return None
    if any(ord(char) <= 32 or ord(char) >= 127 for char in value):
        return None
    if any(char in value for char in ("%", "\\", "?", "#", "@")):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    host = parts.netloc
    if (
        parts.scheme != "https"
        or not DNS_HOST.fullmatch(host)
        or len(host) > 253
        or parts.path != path
        or value != f"https://{host}{path}"
    ):
        return None
    # Canonical lowercase ASCII DNS names, default port only; no IP literals.
    # This is syntax checking, not a DNS/public-routing or certificate proof.
    if (
        host.rsplit(".", 1)[-1].isdigit()
        or host.endswith((".localhost", ".local"))
        or host == "localhost"
    ):
        return None
    return host


def _summary(result: str, errors: list[str], missing: list[str]) -> dict[str, Any]:
    return {
        "schemaVersion": "RIO_STAGING_PREFLIGHT_RESULT_V1",
        "result": result,
        "errors": sorted(set(errors)),
        "missing": sorted(set(missing)),
        "checks": {
            "networkProbesPerformed": False,
            "dnsVerified": False,
            "tlsVerified": False,
            "providerMetadataVerified": False,
            "sourceVerified": False,
            "artifactDigestsVerified": False,
        },
        "boundary": {
            "launchSupported": False,
            "deployAllowed": False,
            "account1": "HOLD",
            "humanAcceptance": "HOLD",
            "personalAccounts": False,
            "publicRegistration": False,
            "contact": False,
            "operativeAuthority": "NONE",
            "deployment": "HOLD",
        },
    }


def assess(plan: Any) -> dict[str, Any]:
    """Check proposal structure only. Never trust caller-supplied readiness flags."""
    required = set(FIXED) | {"source", "endpoints", "artifacts"}
    if not _keys(plan, required):
        return _summary("REJECTED", ["SCHEMA"], [])
    errors: list[str] = []
    missing: list[str] = []
    for key, expected in FIXED.items():
        if not _same(plan[key], expected):
            errors.append("CLOSED_BOUNDARY" if key == "boundary" else "POLICY")
    source = plan["source"]
    if (
        not _keys(source, SOURCE_KEYS)
        or source["repository"] != "Maurits-pixe/PALACO"
        or type(source["commit"]) is not str
        or not COMMIT.fullmatch(source["commit"])
    ):
        errors.append("SOURCE")

    endpoints = plan["endpoints"]
    hosts: dict[str, str] = {}
    if not _keys(endpoints, set(ENDPOINT_PATHS)):
        errors.append("ENDPOINTS")
    else:
        for key, path in ENDPOINT_PATHS.items():
            value = endpoints[key]
            if value is None:
                missing.append(key)
            else:
                host = _host(value, path)
                if host is None:
                    errors.append("ENDPOINTS")
                else:
                    hosts[key] = host
        bff = hosts.get("bffOrigin")
        idp = hosts.get("idpIssuer")
        callback = hosts.get("callbackUrl")
        if bff and callback and callback != bff:
            errors.append("CALLBACK_BINDING")
        if bff and idp and bff == idp:
            errors.append("COOKIE_HOST_ISOLATION")
        if idp and any(
            hosts.get(key) is not None and hosts[key] != idp
            for key in ("discoveryUrl", "authorizationUrl", "tokenUrl", "jwksUrl")
        ):
            errors.append("PROVIDER_BINDING")

    artifacts = plan["artifacts"]
    if not _keys(artifacts, set(ARTIFACT_PATTERNS)):
        errors.append("ARTIFACTS")
    else:
        for key, pattern in ARTIFACT_PATTERNS.items():
            value = artifacts[key]
            if value is None:
                missing.append(key)
            elif type(value) is not str or not pattern.fullmatch(value):
                errors.append("ARTIFACTS")
    if errors:
        return _summary("REJECTED", errors, missing)
    if missing:
        return _summary("INCOMPLETE", [], missing)
    return _summary("CONFIGURATION_CONSISTENT", [], [])


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(_: str) -> Any:
    raise ValueError("non-finite JSON")


def assess_bytes(raw: bytes) -> dict[str, Any]:
    """Bounded UTF-8 JSON; every failure produces fixed categories, not raw input."""
    if type(raw) is not bytes or len(raw) > LIMIT:
        return _summary("REJECTED", ["INPUT"], [])
    try:
        plan = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        return assess(plan)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        return _summary("REJECTED", ["INPUT"], [])


def read_plan(path: str) -> dict[str, Any]:
    """Read one bounded regular file. No output is written to a caller-chosen path."""
    descriptor = None
    try:
        if type(path) is not str or path.startswith(("\\\\", "//")) or "\x00" in path:
            raise ValueError("local path required")
        if os.path.islink(path):
            raise ValueError("symlink")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > LIMIT:
            raise ValueError("regular bounded file required")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            raw = source.read(LIMIT + 1)
        return assess_bytes(raw)
    except (OSError, ValueError, TypeError, OverflowError):
        return _summary("REJECTED", ["INPUT"], [])
    finally:
        if descriptor is not None:
            os.close(descriptor)


def main() -> int:
    result = (
        read_plan(sys.argv[1])
        if len(sys.argv) == 2
        else _summary("REJECTED", ["INPUT"], [])
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return {
        "CONFIGURATION_CONSISTENT": 0,
        "INCOMPLETE": 2,
        "REJECTED": 3,
    }[result["result"]]


if __name__ == "__main__":
    raise SystemExit(main())
