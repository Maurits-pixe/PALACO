# RIO T05 — page versus context session-boundary differential

### Status
DRAFT / SYNTHETIC_ONLY / NEGATIVE ENGINEERING TEST / ROOT CAUSE UNKNOWN / ACCEPTANCE HOLD.

### Last Updated
2026-10-14

## Hypotheses, not conclusions

In the current loopback-only synthetic RIO service, PostgreSQL sessions are kept with a hard **30-second idle expiry** and **60-second absolute expiry** (`services/rio-accounts/src/storage.rs`). The absolute deadline is not extended by any read. The application uses browser-document `fetch('/api/me')` for its own UI access; the `nativeConsent` helper checks the committed consent response and database readback via the browser context's request channel. These two request paths may behave differently if a page's JavaScript/network context is interrupted. They share the same cookies but are **not interchangeable authorization grants**.

Historical Android test run [#38587411896](https://github.com/Maurits-pixe/PALACO/actions/runs/38587411896) failed at the strict post-consent `/api/me` HTTP 200 assertion without recording the actual status. Later error-injection tests [draft #62](https://github.com/Maurits-pixe/PALACO/pull/62) on `4843c7b9` verified that deliberately injected HTTP 401 and connection resets are observed without silent retry. **Neither a real session expiration nor a page-context loss was proven as the original cause.**

## Differential controlled test

New synthetic `RIO-MOBILE-10`, in `verification/rio-accounts/mobile/post-consent-context.spec.mjs`, runs once under Android emulation and desktop keyboard:

1. Log in to the real, disposable loopback Keycloak/BFF with the **synthetic alpha actor**, grant consent and verify that the server committed and read back the same receipt revision. Never create a personal account.
2. Route just the next browser **page-owned GET /api/me** to a deliberate `connectionreset`. Require that the one-shot `postConsentOwnAccountRead` propagates failure, intercept count is exactly **1**, and a schema-validated failure annotation includes **only** the bounded receipt revisions, request-failure flag and cookie-presence Boolean; no bearer, URL, credentials, OIDC code or raw error.
3. Stop the fault injection. Perform one **explicit diagnostic context-channel GET /api/me** using the same browser context and cookie jar; verify HTTP **200**, account `TST-alpha`, `SYNTHETIC_ONLY`, `accountActive=false`, `canOpenContact=false`, `account1=HOLD`, `operativeAuthority=NONE`. This extra diagnostic GET is permitted **only in this dedicated negative test**, not the ordinary `RIO-MOBILE-01` flow, and never considered an automatic recovery of the failed page read.
4. Require that the intercepted browser GET count stayed at one. The original `RIO-MOBILE-01` still strictly requires its first own-account GET to be HTTP 200; no retry, timeout, cookie scope, session expiry or auth decision is relaxed.

**Interpretation:** A deliberate page-network fault with a still-valid server session proves the diagnostic distinction `PAGE_FETCH_FAILED ≠ SERVER_SESSION_REVOKED`. It does **not** establish that the historical intermittent failure was a page-network problem. A naturally expired idle/absolute session must still deny access. No session extension or recovery authority is added.

## Acceptance and boundaries

A full exact-head CI run must independently pass the targeted browser case on Android and desktop **and** all existing Keycloak/OIDC, PostgreSQL TLS/issuer-subject binding, consent, revocation, backup/restore, reflow and Studio tests. GO-13 is also mandatory. The new test is on a **separate stacked DRAFT** from parent PR #62 head `4843c7b912dcd7846617343391b3f04ae2a95f8b`.

[Post-consent investigation #60](https://github.com/Maurits-pixe/PALACO/issues/60) and [login-transport investigation #51](https://github.com/Maurits-pixe/PALACO/issues/51) remain OPEN / ROOT CAUSE UNKNOWN. Human acceptance [#50](https://github.com/Maurits-pixe/PALACO/issues/50), ACCOUNT-1, physical device tests, real identities, NOVA contact, staging and production remain HOLD. No merge, deployment, publication or spending is authorized.

`DIFFERENTIAL TEST PASS ≠ HISTORICAL CAUSE FOUND ≠ AUTHORIZATION`.
