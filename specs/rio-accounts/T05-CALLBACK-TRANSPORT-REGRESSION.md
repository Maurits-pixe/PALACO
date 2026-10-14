# RIO — interrupted callback fail-closed regression

### Status
DRAFT / SYNTHETIC_ONLY / EXPERIMENTAL ENGINEERING EVIDENCE / HUMAN ACCEPTANCE HOLD.

### Last Updated
2026-10-14

## Grounded observation, not an inferred cause

[PR #57 full synthetic run #38565603164, attempt 1](https://github.com/Maurits-pixe/PALACO/actions/runs/38565603164) failed during Android-emulated `RIO-MOBILE-01`. Its bounded login observation reported:

- `actorCase=alpha`, `stage=waiting-for-bff`, `pageKind=provider`;
- `errorKind=network-changed`, `documentStatuses=[200]`;
- `meStatuses=[401]`, `meRequestFailed=true`, `accountVisible=null`.

The [same-SHA rerun attempt 2](https://github.com/Maurits-pixe/PALACO/actions/runs/38565603164) passed the complete real Keycloak/PostgreSQL/TLS/mobile integration suite. **These are independent results and do not explain why the first browser observed network transport change.** Login intermittency remains [issue #51](https://github.com/Maurits-pixe/PALACO/issues/51) OPEN.

## Controlled negative test

The new `verification/rio-accounts/mobile/callback-interruption.spec.mjs`, case `RIO-MOBILE-07`, injects an explicit Chromium `connectionreset` only on the real loopback `/auth/callback` navigation, **before** the BFF can exchange or commit the received OIDC authorization code. This tests a **related transport-failure boundary**, not a reproduction of spontaneous `ERR_NETWORK_CHANGED` or evidence of its root cause.

The test requires all of the following:
1. An actual Keycloak OIDC/PKCE login reaches the callback and fails once, with no unrequested second `/auth/start`.
2. The allowlisted failure observation records only synthetic actor, lifecycle stage, page category and error kind; no callback URL, query code, cookies, raw exception or personally identifiable data is attached or printed.
3. A separate cookie-bound request to `/api/me` is `401`, and the BFF has not set `__Host-rio_session`; no authority is inferred from provider-side login.
4. Only **after removing the fault** does a completely new, explicitly initiated login pass; that login must preserve `accountActive=false`, `canOpenContact=false`, consent-scope and no persistent browser storage.
5. The case runs once under each configured emulated Android touch and desktop-keyboard project with **retries=0** and existing timeouts. The other T05 synthetic TLS, issuer/subject/account binding and revocation tests remain mandatory on the new candidate head.

Unexpected failures remain FAIL. No timeout extension, silent retry, OIDC-code replay, real phone/provider test, active user account, staging connector or deployment is authorized by this test.

## Gate

The existing [T05 TLS/subject binding PR #57](https://github.com/Maurits-pixe/PALACO/pull/57) retains its own frozen tested head `0419120282b8ccf1b5f1d4353b9450e384f4f010`. This continuation must remain a **new, separate stacked DRAFT PR** based on that head. A green test confirms only bounded fail-closed handling of an intentionally dropped callback. Root-cause investigation #51 and independent human accessibility/security/privacy/operations review [#50](https://github.com/Maurits-pixe/PALACO/issues/50) remain OPEN.

`T05_ENGINEERING_TEST ≠ LOGIN_ROOT_CAUSE_REPAIRED ≠ HUMAN_ACCEPTANCE ≠ STAGING_AUTHORIZED`.

ACCOUNT-1, real identities, invitations, NOVA contact, physical-device access, staging and production remain **HOLD**.
