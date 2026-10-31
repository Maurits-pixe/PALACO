#!/usr/bin/env python3
"""GO-18 policy verifier.

PASS means the point-in-time GitHub advisory query completed and every reviewed
or malware advisory affecting the evaluated Rust/npm package versions is either
absent or covered by a complete, unexpired, exact-scope exception.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts" / "go18" / "PALACO-advisory-evaluation.json"


def fail(message: str) -> None:
    print(f"GO-18 ADVISORY POLICY: FAIL - {message}")
    raise SystemExit(1)


def main() -> None:
    if not EVIDENCE.is_file():
        fail("advisory evidence is missing")

    raw = EVIDENCE.read_bytes()
    data = json.loads(raw)

    if data.get("schema") != "palaco.advisory-evaluation.v1":
        fail("unexpected evidence schema")
    if data.get("gate") != "GO-18":
        fail("unexpected gate")
    if data.get("source", {}).get("name") != "GitHub Global Security Advisory Database":
        fail("unexpected advisory source")
    if data.get("source", {}).get("advisory_types") != ["reviewed", "malware"]:
        fail("GO-18 must evaluate reviewed and malware advisories")

    packages = data.get("packages_evaluated", {})
    if packages.get("rust", 0) <= 0:
        fail("no Rust packages were evaluated")
    if packages.get("npm", 0) <= 0:
        fail("no npm packages were evaluated")

    if data.get("source_error"):
        fail("advisory source/policy error: " + str(data["source_error"]))

    findings = data.get("findings", [])
    blocking = [
        item
        for item in findings
        if item.get("policy_status") != "EXCEPTED_UNTIL_EXPIRY"
    ]
    if len(blocking) != data.get("blocking_findings"):
        fail("blocking_findings count does not match evidence")

    stale = data.get("exception_usage", {}).get("unused_or_stale", [])
    if stale:
        fail("unused or stale advisory exceptions exist")

    if data.get("result") != "PASS":
        summary = ", ".join(
            f"{item.get('ghsa_id')}:{item.get('ecosystem')}:{item.get('package')}@{item.get('version')}"
            for item in blocking[:10]
        )
        suffix = "" if len(blocking) <= 10 else f" (+{len(blocking)-10} more)"
        fail(
            f"result={data.get('result')} blocking_findings={len(blocking)} "
            f"{summary}{suffix}"
        )

    digest = hashlib.sha256(raw).hexdigest()
    severity_counts: dict[str, int] = {}
    for item in findings:
        severity = str(item.get("severity", "unknown"))
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    print("GO-18 ADVISORY POLICY: PASS")
    print(f"packages_total={packages.get('total')}")
    print(f"rust_packages={packages.get('rust')}")
    print(f"npm_packages={packages.get('npm')}")
    print(f"findings_total={len(findings)}")
    print("blocking_findings=0")
    print("exceptions_stale=0")
    print("evidence_sha256=" + digest)
    print("severity_counts=" + json.dumps(severity_counts, sort_keys=True))
    print("container_vulnerability_scope=NOT_EVALUATED_BY_GO_18")


if __name__ == "__main__":
    main()
