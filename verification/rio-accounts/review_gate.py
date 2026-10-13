"""Validate a redacted T04 review record without issuing human authority.

This checker is schema/consistency tooling, *not* attestation or acceptance.
It never prints input fields, so rejected packages cannot leak private data via CI.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

SCHEMA = "rio-t04-human-evidence/v1"
ALLOWED_STATUS = frozenset({"NOT_RUN", "BLOCKED", "FAIL", "PASS"})
ALLOWED_REASONS = frozenset({
    "NOT_YET_RUN", "PHYSICAL_PATH_NOT_AUTHORIZED", "NEEDS_HUMAN_REVIEW",
    "TEST_FAILED", "OPEN_SECURITY_FINDING", "NONE",
})
CASES = {
    **{f"H04-A{i:02d}": "ACCESSIBILITY" for i in range(1, 8)},
    "H04-SEC": "SECURITY",
    "H04-PRIV": "PRIVACY",
    "H04-OPS": "OPERATIONS",
    "H04-GOV": "GOVERNANCE",
}
PHYSICAL_CASES = frozenset(f"H04-A{i:02d}" for i in range(1, 6))
SHA = re.compile(r"[0-9a-f]{40}\Z")
EVIDENCE = re.compile(r"EVD-[A-Z0-9-]{4,48}\Z")
FINDING = re.compile(r"FND-[0-9]{4,8}\Z")


class InvalidEvidence(ValueError):
    """The sanitized review package violates the structural contract."""


def _exact(obj: object, keys: set[str]) -> bool:
    return type(obj) is dict and set(obj) == keys


def validate(record: object) -> dict[str, object]:
    """Validate strictly; NEVER return a grant, approval or reviewer signature."""
    if not _exact(record, {
        "schema", "repo", "pr", "candidateHead", "baseSha", "scope",
        "account1", "authority", "humanAcceptance", "physicalAccess", "cases",
    }):
        raise InvalidEvidence("invalid envelope")
    assert isinstance(record, dict)
    if (record["schema"] != SCHEMA or record["repo"] != "Maurits-pixe/PALACO"
        or type(record["pr"]) is not int or record["pr"] != 49
        or record["scope"] != "SYNTHETIC_ONLY" or record["account1"] != "HOLD"
        or record["authority"] != "NONE" or record["humanAcceptance"] != "HOLD"
        or record["physicalAccess"] not in {"NOT_AUTHORIZED", "HUMAN_ATTESTED_SYNTHETIC_ONLY"}
        or not isinstance(record["candidateHead"], str) or not SHA.fullmatch(record["candidateHead"])
        or not isinstance(record["baseSha"], str) or not SHA.fullmatch(record["baseSha"])):
        raise InvalidEvidence("invalid authority boundary")

    cases = record["cases"]
    if type(cases) is not list or len(cases) != len(CASES):
        raise InvalidEvidence("case coverage not complete")
    encountered = set()
    totals = {status: 0 for status in sorted(ALLOWED_STATUS)}
    for item in cases:
        if not _exact(item, {
            "id", "status", "reason", "reviewerRole", "independenceAttested",
            "evidenceIds", "findingIds",
        }):
            raise InvalidEvidence("invalid case record")
        name = item["id"]
        if type(name) is not str or name not in CASES or name in encountered:
            raise InvalidEvidence("unknown or repeated case")
        encountered.add(name)
        status = item["status"]
        role = item["reviewerRole"]
        reason = item["reason"]
        refs = item["evidenceIds"]
        findings = item["findingIds"]
        if (type(status) is not str or status not in ALLOWED_STATUS
            or type(reason) is not str or reason not in ALLOWED_REASONS
            or type(role) is not str or role not in {"UNASSIGNED", CASES[name]}
            or type(item["independenceAttested"]) is not bool
            or type(refs) is not list or len(refs) > 12
            or any(type(x) is not str or not EVIDENCE.fullmatch(x) for x in refs)
            or len(refs) != len(set(refs))
            or type(findings) is not list or len(findings) > 12
            or any(type(x) is not str or not FINDING.fullmatch(x) for x in findings)
            or len(findings) != len(set(findings))):
            raise InvalidEvidence("invalid evidence reference")
        if status == "PASS":
            if (role != CASES[name] or item["independenceAttested"] is not True
                or not refs or findings or reason != "NONE"):
                raise InvalidEvidence("unsupported PASS claim")
            if name in PHYSICAL_CASES and record["physicalAccess"] != "HUMAN_ATTESTED_SYNTHETIC_ONLY":
                raise InvalidEvidence("physical PASS requires human access attestation")
        elif status == "FAIL":
            if role != CASES[name] or not refs or not findings or reason not in {
                "TEST_FAILED", "OPEN_SECURITY_FINDING",
            }:
                raise InvalidEvidence("unsubstantiated FAIL")
        else:
            if (role != "UNASSIGNED" or item["independenceAttested"] is not False
                or refs or findings or reason == "NONE"):
                raise InvalidEvidence("incomplete case wrongly claims review evidence")
            if status == "BLOCKED" and reason not in {"PHYSICAL_PATH_NOT_AUTHORIZED", "NEEDS_HUMAN_REVIEW"}:
                raise InvalidEvidence("blocked case lacks blocker")
            if status == "NOT_RUN" and reason not in {"NOT_YET_RUN", "NEEDS_HUMAN_REVIEW"}:
                raise InvalidEvidence("unrun case reason mismatch")
        totals[status] += 1
    if encountered != set(CASES):
        raise InvalidEvidence("missing required case")
    # A real reviewer can attest independence, but no data package proves
    # identity/competence/approval. Human gate remains HOLD even if all PASS.
    return {"schema": SCHEMA, "structure": "VALID", "humanAcceptance": "HOLD",
            "physicalAndroidVerified": False, "independentReviewAccepted": False,
            "statuses": totals}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise InvalidEvidence("duplicate JSON key")
        result[name] = value
    return result


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 2:
            raise InvalidEvidence("missing record")
        path = Path(argv[1])
        if not path.is_file() or path.stat().st_size > 16384:
            raise InvalidEvidence("input size")
        with path.open("r", encoding="utf-8") as source:
            record = json.load(source, object_pairs_hook=_reject_duplicate_keys)
        report = validate(record)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        print("RIO_T04_REVIEW_RECORD REJECTED")
        return 1
    print("RIO_T04_REVIEW_RECORD " + json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
