#!/usr/bin/env python3
"""Summarize a GO-19 remediation candidate Trivy report.

This is exploratory evidence only. It never grants an exception and never
changes the GO-19 conformance result.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument("--report", required=True)
parser.add_argument("--ref-file", required=True)
args=parser.parse_args()

report=json.loads(Path(args.report).read_text(encoding="utf-8"))
resolved=Path(args.ref_file).read_text(encoding="utf-8").strip()

counts={}
blocking=[]
for result in report.get("Results") or []:
    for vuln in result.get("Vulnerabilities") or []:
        sev=str(vuln.get("Severity") or "UNKNOWN").upper()
        counts[sev]=counts.get(sev,0)+1
        if sev in {"CRITICAL","HIGH","UNKNOWN"}:
            blocking.append({
                "id":vuln.get("VulnerabilityID"),
                "package":vuln.get("PkgName"),
                "installed":vuln.get("InstalledVersion"),
                "fixed":vuln.get("FixedVersion"),
                "severity":sev,
            })

print("GO-19R CANDIDATE SCAN: RECORDED")
print("resolved_ref="+resolved)
print("severity_counts="+json.dumps(counts,sort_keys=True))
print("blocking_findings="+str(len(blocking)))
for item in blocking[:20]:
    print(
        "BLOCK: {id} {package}@{installed} fixed={fixed} severity={severity}".format(**item)
    )
