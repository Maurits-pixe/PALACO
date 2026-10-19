# RIO T05 — post-consent own-account read evidence

### Status
DRAFT / SYNTHETIC_ONLY / TEST-ONLY INSTRUMENTATION / CAUSE UNKNOWN / HUMAN ACCEPTANCE HOLD.

### Last Updated
2026-10-14

## Trigger and scope of proof

At [T05 CI #38587411896](https://github.com/Maurits-pixe/PALACO/actions/runs/38587411896), exact earlier diagnostic candidate `ebb99c4a5acae427f5d408a36e7b166ce634dbdd`, the existing Android-emulated `RIO-MOBILE-01` failed in `mobile-native-semantics` at the **strict HTTP 200 requirement on the next `/api/me` GET after a granted and durably read-back consent receipt** (`interaction.spec.mjs`, previously source line 66). The safe reporter preserved source lines but **did not provide the actual divergent status**. The Android `RIO-MOBILE-02` preparation probe (8/8) and desktop `RIO-MOBILE-01` passed. Issue [#60](https://github.com/Maurits-pixe/PALACO/issues/60) tracks this separate observation, not established as the same cause as [login/callback issue #51](https://github.com/Maurits-pixe/PALACO/issues/51).

## Candidate: one-shot, failure-only evidence

Add `verification/rio-accounts/post-consent-observation.mjs` and its negative unit tests. The `RIO-MOBILE-01` test continues to make **exactly one** client-side `/api/me` read following the already committed consent grant and verified receipt. No retries, extra account GETs, cookie scope changes, server writes, browser timeout changes or service-side authorization changes are introduced.

**Only when that one account read fails** (non-200 status or rejected request), the test emits a strict allowlisted annotation with exactly:
- `stage=after-grant`, `grantRevision`, `storedRevision` (bounded, synthetic receipt revision integers);
- `accountStatus` (actual HTTP integer 100–599, or null on a thrown request);
- `accountRequestFailed` Boolean and `errorKind` from the existing enum (never a raw exception);
- `sessionCookiePresent` Boolean, or null if the cookie jar cannot be inspected. **Never the cookie value.**

A dedicated validator rejects missing/unknown/secret-bearing fields, malformed status/revisions, duplicate annotations and fabricated successful-status failure reports. The safe Playwright reporter exports this annotation only for **failed `RIO-MOBILE-01`**. If the request is successful and returns 200, no annotation is added. The existing `expect(account.status).toBe(200)` and own-account actor/authority assertions remain **unaltered in meaning**. If a transport exception occurs, the same exception is rethrown to the test so the case remains FAIL.

The emitted failure metadata can distinguish a real 401/403/5xx from a missing browser execution context, but cannot establish root cause or prove state consistency. A consent receipt revision itself never grants an identity or releases an account.

## Acceptance and controls

The candidate must pass independent Node privacy tests and the exact-head integrated real Keycloak + PostgreSQL TLS + issuer/subject binding, mobile/desktop Playwright, session recovery/revocation and backup/restore suite. **A clean run without the sporadic failure validates instrumentation coverage, not repair.** A future failing run with a safe annotation supplies evidence to analyze separately; it does not justify silent retries or weakening a 200 assertion.

Parent PR [#59](https://github.com/Maurits-pixe/PALACO/pull/59) remains DRAFT/UNMERGED. This is a new stacked DRAFT PR from exact `ebb99c4a5acae427f5d408a36e7b166ce634dbdd`, with no change to Rust, Keycloak, PostgreSQL TLS, account/consent rules or deployment. Independent human T04 acceptance [#50](https://github.com/Maurits-pixe/PALACO/issues/50), ACCOUNT-1, physical Android accounts, invitations, NOVA contact, staging and production stay HOLD.

`RECORDED FAILURE ≠ DIAGNOSED CAUSE ≠ FIXED CAUSE ≠ RELEASE AUTHORITY`.
