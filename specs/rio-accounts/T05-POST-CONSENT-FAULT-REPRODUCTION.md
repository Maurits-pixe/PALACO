# RIO T05 — deterministic post-consent account-read fault reproduction

### Status
DRAFT / SYNTHETIC_ONLY / NEGATIVE TEST CANDIDATE / HUMAN ACCEPTANCE HOLD.

### Last Updated
2026-10-14

## Evidence basis

The historical [RIO CI #38587411896](https://github.com/Maurits-pixe/PALACO/actions/runs/38587411896) failed in an existing Android `RIO-MOBILE-01` on the strict post-consent `/api/me` HTTP 200 assertion; the unexpected status was not captured. The subsequent isolated instrumentation [draft PR #61](https://github.com/Maurits-pixe/PALACO/pull/61), exact head `fc885c94e7ffd7dd686d14a8271d1fea1e356733`, passed full synthetic CI, but no spontaneous failure reappeared. The root cause therefore remains UNKNOWN under [issue #60](https://github.com/Maurits-pixe/PALACO/issues/60). Pre-/mid-login transport intermittency is investigated separately in [issue #51](https://github.com/Maurits-pixe/PALACO/issues/51).

## Independent, intentionally injected browser faults

New real local-Keycloak browser suite `mobile/post-consent-fault.spec.mjs`, included on Android Chromium emulation and desktop keyboard. The setup logs into the **synthetic** alpha account, obtains its existing consent receipt, grants consent through the actual BFF API and reads back the committed revision. Only **then** does the test install a scoped browser route for one `GET /api/me`. No server, OIDC, TLS, consent or database code changes.

- **RIO-MOBILE-08 / HTTP denial:** the first post-grant `/api/me` GET gets an injected HTTP **401** with a fixed synthetic nonsecret body. Assert the helper returns precisely HTTP 401, not a manufactured 200; account JSON is null; exactly one GET was intercepted. The failure-only diagnostic contains the expected consent revisions, 401, `accountRequestFailed=false`, and session-cookie **presence Boolean only**.
- **RIO-MOBILE-09 / transport reset:** the first post-grant `/api/me` GET is aborted using Playwright `connectionreset`. Assert the **same original exception** propagates from the diagnostic wrapper, the one-shot read is not silently retried, and the diagnostic records `accountStatus=null`, `accountRequestFailed=true` and a fixed allowlisted error kind (never raw exception).
- Both negative cases check exactly the keys of the schema-validated failure record and no account identity, URL, cookie value, CSRF bearer, OIDC token, response text or personal data. They are run without test retries or altered timeouts.
- The standard **RIO-MOBILE-01** strict HTTP 200 expectation remains untouched, as do its correct-account and `accountActive=false` / `canOpenContact=false` assertions. The negative cases test the **test harness and instrumentation** only: injected route responses do not prove that the real BFF would intermittently return 401 or drop a connection.

The safe reporter enumerates RIO-MOBILE-08/09 as fixed cases, with fixed phase IDs. A complete exact-head RIO workflow (native Rust, PostgreSQL TLS, real loopback Keycloak, consent, durable revoke, backup/restore, Android and desktop) and GO-13 must pass before calling this candidate engineering PASS.

## Constitutional boundary

This is a **separate stacked draft** from the frozen [PR #61](https://github.com/Maurits-pixe/PALACO/pull/61) head `fc885c94e7ffd7dd686d14a8271d1fea1e356733`. It is neither root-cause repair nor proof of intermittent incident reproducibility under natural conditions. Negative historical runs remain untouched. The actual cause of #60 and #51 remains UNKNOWN.

**No merge / no deployment / no real accounts / no new identity or NOVA-contact authority / no staging / no production.** T04 independent [human acceptance #50](https://github.com/Maurits-pixe/PALACO/issues/50) remains OPEN and is required separately from software CI.

`INJECTED FAILURE ≠ HISTORICAL CAUSE ≠ FIX ≠ AUTHORIZED RELEASE`.
