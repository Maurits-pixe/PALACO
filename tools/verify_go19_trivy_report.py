#!/usr/bin/env python3
"""Evaluate one GO-19 Trivy JSON report against PALACO policy."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "evidence" / "governance" / "GO-19-CONTAINER-VULNERABILITY-POLICY.json"
EXCEPTIONS = ROOT / "evidence" / "governance" / "GO-19-CONTAINER-VULNERABILITY-EXCEPTIONS.json"


def parse_expiry(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("expiry must be UTC and end in Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def exception_key(item: dict, image: str | None = None) -> tuple[str, str, str, str]:
    return (
        str(item.get("vulnerability_id") or item.get("VulnerabilityID") or ""),
        str(item.get("image") or image or ""),
        str(item.get("package") or item.get("PkgName") or ""),
        str(item.get("installed_version") or item.get("InstalledVersion") or ""),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    report_path = Path(args.report)
    evidence_path = Path(args.evidence)
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    exception_doc = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
    report_raw = report_path.read_bytes()
    report = json.loads(report_raw)

    errors: list[str] = []
    if args.image not in policy.get("images", []):
        errors.append("scanned image is not in GO-19 policy")

    blocking_severities = set(policy.get("blocking_severities", []))
    report_results = report.get("Results")
    if not isinstance(report_results, list):
        errors.append("Trivy report lacks Results list")
        report_results = []

    vulnerabilities: list[dict] = []
    for result in report_results:
        target = result.get("Target")
        vuln_class = result.get("Class")
        vuln_type = result.get("Type")
        for vuln in result.get("Vulnerabilities") or []:
            item = {
                "vulnerability_id": vuln.get("VulnerabilityID"),
                "package": vuln.get("PkgName"),
                "installed_version": vuln.get("InstalledVersion"),
                "fixed_version": vuln.get("FixedVersion"),
                "severity": str(vuln.get("Severity") or "UNKNOWN").upper(),
                "title": vuln.get("Title"),
                "primary_url": vuln.get("PrimaryURL"),
                "target": target,
                "class": vuln_class,
                "type": vuln_type,
            }
            vulnerabilities.append(item)

    raw_exceptions = exception_doc.get("exceptions", [])
    exception_map: dict[tuple[str, str, str, str], dict] = {}
    for item in raw_exceptions:
        key = exception_key(item)
        if key in exception_map:
            errors.append(f"duplicate exception identity: {key}")
        exception_map[key] = item

    current = datetime.now(timezone.utc)
    used: set[tuple[str, str, str, str]] = set()
    blocking: list[dict] = []
    excepted: list[dict] = []
    severity_counts: dict[str, int] = {}

    for vuln in vulnerabilities:
        severity = vuln["severity"]
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        if severity not in blocking_severities:
            vuln["policy_status"] = "RECORDED_NON_BLOCKING"
            continue

        key = exception_key(vuln, args.image)
        exception = exception_map.get(key)
        if exception is None:
            vuln["policy_status"] = "BLOCK"
            blocking.append(vuln)
            continue

        required = ["expires_at", "rationale", "approved_by", "evidence"]
        missing = [field for field in required if not exception.get(field)]
        if missing:
            vuln["policy_status"] = "BLOCK_INCOMPLETE_EXCEPTION"
            vuln["exception_missing"] = missing
            blocking.append(vuln)
            continue

        try:
            expiry = parse_expiry(str(exception["expires_at"]))
        except Exception as exc:
            vuln["policy_status"] = "BLOCK_INVALID_EXCEPTION_EXPIRY"
            vuln["exception_error"] = str(exc)
            blocking.append(vuln)
            continue

        if expiry <= current:
            vuln["policy_status"] = "BLOCK_EXPIRED_EXCEPTION"
            blocking.append(vuln)
            continue

        vuln["policy_status"] = "EXCEPTED_UNTIL_EXPIRY"
        vuln["exception_expires_at"] = exception["expires_at"]
        used.add(key)
        excepted.append(vuln)

    stale_for_image = sorted(
        key
        for key in exception_map
        if key[1] == args.image and key not in used
    )
    if stale_for_image:
        errors.append(
            "unused/stale exceptions for image: "
            + json.dumps([list(key) for key in stale_for_image])
        )

    evaluation = {
        "schema": "palaco.container-vulnerability-evaluation.v1",
        "gate": "GO-19",
        "image": args.image,
        "scanner": policy.get("scanner"),
        "blocking_severities": sorted(blocking_severities),
        "report_sha256": hashlib.sha256(report_raw).hexdigest(),
        "vulnerabilities_total": len(vulnerabilities),
        "severity_counts": severity_counts,
        "blocking_findings": blocking,
        "excepted_findings": excepted,
        "stale_exceptions": [list(key) for key in stale_for_image],
        "policy_errors": errors,
        "result": "PASS" if not blocking and not errors else "BLOCKED",
        "non_claims": [
            "PASS does not prove absence of unknown or zero-day vulnerabilities.",
            "MEDIUM and LOW findings are recorded but are not blocking in GO-19.",
            "GO-19 does not establish runtime exploitability.",
        ],
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evaluation, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    if blocking or errors:
        print("GO-19 CONTAINER VULNERABILITY POLICY: BLOCKED")
        print(f"image={args.image}")
        print(f"vulnerabilities_total={len(vulnerabilities)}")
        print(f"blocking_findings={len(blocking)}")
        print("severity_counts=" + json.dumps(severity_counts, sort_keys=True))
        for item in blocking[:20]:
            print(
                "BLOCK: "
                + f"{item.get('vulnerability_id')} "
                + f"{item.get('package')}@{item.get('installed_version')} "
                + f"severity={item.get('severity')}"
            )
        for error in errors:
            print("ERROR: " + error)
        raise SystemExit(1)

    print("GO-19 CONTAINER VULNERABILITY POLICY: PASS")
    print(f"image={args.image}")
    print(f"vulnerabilities_total={len(vulnerabilities)}")
    print("blocking_findings=0")
    print(f"excepted_findings={len(excepted)}")
    print("stale_exceptions=0")
    print("severity_counts=" + json.dumps(severity_counts, sort_keys=True))
    print("report_sha256=" + evaluation["report_sha256"])


if __name__ == "__main__":
    main()
