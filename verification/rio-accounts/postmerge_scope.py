"""Fail-closed, source-level HOLD drift detector for the synthetic RIO slice.

Only checks the enumerated source/text boundaries. Not runtime assurance,
independent review, release authorization, or evidence that production is safe.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
PATHS = {
    "server": "services/rio-accounts/src/lib.rs",
    "listener": "services/rio-accounts/src/main.rs",
    "consent": "services/rio-accounts/src/consent_http.rs",
    "fixture": "verification/rio-accounts/fixture.py",
    "gate": "specs/rio-accounts/T04-ACCEPTANCE-GATE.md",
    "workflow": ".github/workflows/rio-accounts-synthetic.yml",
}
EXPECTED_HOLD_FIELDS = (
    '"account1":"HOLD"',
    '"accountActive":false',
    '"operativeAuthority":"NONE"',
    '"canOpenContact":false',
)
CHECKS = (
    "fixed_https_bff_origin", "fixed_synthetic_issuer", "synthetic_mode_required",
    "fixed_loopback_listener", "listener_hold_banner",
    "server_status_closed", "own_account_closed", "own_account_session_bound",
    "consent_receipt_closed", "consent_session_bound",
    "synthetic_fixture_issuer", "synthetic_fixture_callback",
    "fixture_registration_disabled", "review_gate_hold", "ci_read_only_token",
)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def region(content: str, start: str, end: str) -> str:
    if content.count(start) != 1 or content.count(end) != 1:
        return ""
    return compact(content.split(start, 1)[1].split(end, 1)[0])


def check_sources(source: dict[str, str]) -> dict[str, bool]:
    """Return only closed-schema boolean findings; no raw source or secrets."""
    if set(source) != set(PATHS) or any(type(value) is not str for value in source.values()):
        raise ValueError("incomplete source manifest")
    srv = compact(source["server"])
    listener = compact(source["listener"])
    fixture = compact(source["fixture"])
    consent = compact(source["consent"])
    wf = source["workflow"]
    status = region(source["server"], "fn status() -> Value {", "async fn health(")
    me = region(source["server"], "async fn me(", "fn mutation_headers(")
    receipt = region(source["consent"], "fn response(receipt: ConsentRecord)", "pub(crate) async fn read(")
    read = region(source["consent"], "pub(crate) async fn read(", "/// Commit an explicit")
    checks = {
        "fixed_https_bff_origin": 'pubconstORIGIN:&str="https://localhost:8088";' in srv,
        "fixed_synthetic_issuer": 'pubconstISSUER:&str="http://127.0.0.1:8089/realms/rio-synthetic";' in srv,
        "synthetic_mode_required": 'ifmode!="SYNTHETIC_ONLY"' in srv,
        "fixed_loopback_listener": 'SocketAddr::from(([127,0,0,1],8088))' in listener,
        "listener_hold_banner": 'ACCOUNT-1HOLD' in listener and 'SYNTHETIC_ONLY:' in listener,
        "server_status_closed": all(item in status for item in EXPECTED_HOLD_FIELDS),
        "own_account_closed": all(item in me for item in EXPECTED_HOLD_FIELDS),
        "own_account_session_bound": 'load_session(hash(&token))' in me
            and 'SESSION_COOKIE' in me and 'UNAUTHORIZED' in me,
        "consent_receipt_closed": all(item in receipt for item in EXPECTED_HOLD_FIELDS),
        "consent_session_bound": 'cookie(&headers,SESSION_COOKIE)' in read
            and 'hash(&token)' in read and 'UNAUTHORIZED' in read,
        "synthetic_fixture_issuer": 'ISSUER="http://127.0.0.1:8089/realms/rio-synthetic"' in fixture,
        "synthetic_fixture_callback": 'CALLBACK="https://localhost:8088/auth/callback"' in fixture,
        "fixture_registration_disabled": '"registrationAllowed":False' in fixture
            and '"resetPasswordAllowed":False' in fixture
            and '"loginWithEmailAllowed":False' in fixture,
        "review_gate_hold": all(x in source["gate"] for x in (
            "HUMAN REVIEW PENDING", "ACCOUNT-1", "HOLD", "physical-device",
        )),
        "ci_read_only_token": bool(re.search(r"(?m)^permissions:\s*\n\s*contents:\s*read\s*$", wf)),
    }
    if tuple(checks) != CHECKS:
        raise ValueError("unexpected scope contract")
    return checks


def read_sources(root: Path) -> dict[str, str]:
    return {key: (root / path).read_text(encoding="utf-8") for key, path in PATHS.items()}


def main() -> int:
    try:
        results = check_sources(read_sources(ROOT))
    except (OSError, UnicodeError, ValueError):
        print("RIO_POST_MERGE_SCOPE FAIL — unreadable or invalid source envelope")
        return 1
    passed = all(results.values())
    # Only controlled check names and booleans, no actual source or runtime data.
    print("RIO_POST_MERGE_SCOPE " + json.dumps({
        "schema": "rio-postmerge-source-scope/v1",
        "status": "PASS" if passed else "FAIL",
        "holdControlsChecked": len(CHECKS),
        "failedCheckIds": [name for name in CHECKS if not results[name]],
        "syntheticOnly": "SOURCE_CONTRACT_ONLY",
        "humanAcceptance": "HOLD",
        "deploymentAcceptance": "HOLD",
        "account1": "HOLD",
    }, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
