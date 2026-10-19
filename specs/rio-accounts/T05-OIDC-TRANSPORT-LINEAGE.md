# RIO T05 — privacy-safe OIDC transport lineage

### Status
DRAFT · SYNTHETIC_ONLY · ENGINEERING DIAGNOSTIC CANDIDATE · ROOT CAUSE UNKNOWN · HUMAN ACCEPTANCE HOLD.

### Last Updated
2026-10-14

## Grounded trigger

On [T05 PR #57 RIO CI #38565603164, first attempt](https://github.com/Maurits-pixe/PALACO/actions/runs/38565603164), the original mobile test `RIO-MOBILE-01` failed at `waiting-for-bff` with `errorKind=network-changed`, provider page still showing, `meStatuses=[401]`, `meRequestFailed=true` and no observed account. The same commit passed on rerun. The [fail-closed negative regression in PR #58](https://github.com/Maurits-pixe/PALACO/pull/58) passed on exact head `86fd3d2e` after intentionally aborting the provider credential POST before callback. This **does not** prove where the spontaneous `ERR_NETWORK_CHANGED` occurs.

## Narrow diagnostic extension

This follow-up branch adds **test-only** counters and bounded HTTP status lists to the *failure-only* `rio-mobile-login-observation` record. Five fixed endpoint categories exist: BFF document GET, BFF `/api/me` GET, BFF `/api/consent` GET, provider credential POST, and BFF callback GET.

Only fixed HTTP **method + scheme/host/port + path** matches are classified. A real callback query contains OIDC authorization data: its parameters, the complete URL and request/response bodies **must never** appear in reporter output or exported CI evidence. The reporter accepts exact known fields and types, at most 8 request events and statuses, and no other annotations.

Added to a *failed login* only:
- `providerSubmitRequests`, `callbackRequests`: integer 0–8 (bounded number of started provider credential POSTs and BFF callback GETs);
- `providerSubmitStatuses`, `callbackStatuses`: up to 8 integer HTTP statuses (100–599), **not** headers/bodies/redirect destinations;
- `providerSubmitRequestFailed`, `callbackRequestFailed`: booleans from Playwright's requestfailure event.

Retain previous document, own-account and consent fixed-status fields, login phase, page kind, user label alpha/beta, whitelisted browser error kind and UI feedback bucket. The tracker is attached to one browser **page** during login and removed after the attempt. There is no durable private-user analytics or network logging.

These breadcrumbs can distinguish, in a future naturally failing attempt, whether the provider submission or callback **started**, was acknowledged at HTTP level or failed at transport. They cannot by themselves locate TCP/TLS/Chromium's underlying root cause, prove a login was successful, or establish authorization.

## First natural failure on this candidate and evidence refinement

The first full RIO run on original candidate head `60105c07`, [workflow #38585882163](https://github.com/Maurits-pixe/PALACO/actions/runs/38585882163), **FAILED** in existing Android-emulated `RIO-MOBILE-02`. The new diagnostic recorded a provider credential POST HTTP 302, BFF callback HTTP 303, account UI not visible, BFF home page, `meStatuses=[401]`, and an account GET transport-failure flag. That **does not establish when the 401 happened**: `/api/me` may initially return 401 before login, and the original status list was not ordered relative to callback.

The follow-up on this same isolated draft adds strictly bounded **post-callback request lineage**, avoiding chronological guesswork:
- `postCallbackMeRequests` and `postCallbackMeStatuses` count only `/api/me` GETs *started after* the browser observed an HTTP 3xx BFF callback response. A private WeakSet ties each response/failure to its actual request.
- `postCallbackMeRequestFailed` is a Boolean for that same specifically tracked subset.
- `sessionCookiePresentAtFailure` is nullable Boolean, derived from a private cookie-jar read at failure time. No cookie value, attributes, session ID or real identity is saved.
- Unit tests cover one initial anonymous 401 preceding callback and a later failed account read, including rejection of private URL/cookie canaries. The synthetic callback-fault browser test requires zero post-callback account requests and no cookie.

The original FAIL remains FAIL and cannot retrospectively be enriched. This instrumentation may help distinguish a future session-cookie issuance problem, a client read race, or a real endpoint rejection; **none of these is currently proven**. The standalone browser interaction may still exhibit intermittent unrelated login failures on the next CI head. No extra retry, softer assertion or reclassification of historical evidence is permitted.

## Negative and positive tests

Node regression tests reject arbitrary raw callback URLs, OIDC codes, credentials, bodies, unknown fields, forged method/host/path, oversized annotations, malformed request counters and HTTP statuses. The controlled `RIO-MOBILE-07` case additionally requires `providerSubmitRequests=1`, `providerSubmitRequestFailed=true`, `callbackRequests=0`, and no callback status after deliberate original-Keycloak-POST interruption. `RIO-MOBILE-06` requires zero provider/callback work on an initial refused BFF navigation. Full exact-head CI must also run real Keycloak, PostgreSQL TLS, session rotation, restart/revoke, backup/restore and all Android/desktop browser tests.

**A future PASS is a diagnostic-conformance PASS only.** It is not a cause-specific fix for the historical failure. Never silently retry, relax assertions or timeouts, widen cookie scope, bypass PKCE, or create accounts to increase success rate.

## Authority boundary

Continuation from [DRAFT PR #58](https://github.com/Maurits-pixe/PALACO/pull/58), on a separate stacked DRAFT PR. The Rust service, Keycloak configuration, TLS connector, session/consent/account binding and deploy mechanisms are unchanged. [Issue #51](https://github.com/Maurits-pixe/PALACO/issues/51) remains OPEN (root cause UNKNOWN); [independent human T04 review #50](https://github.com/Maurits-pixe/PALACO/issues/50) remains OPEN.

`OBSERVED ERROR ≠ IDENTIFIED CAUSE ≠ REMEDIATED CAUSE ≠ HUMAN AUTHORIZATION`.

ACCOUNT-1, real identities, invitations, NOVA contact, external staging, production and physical-device acceptance remain **HOLD**. No merge, hosting or real-user access is implied.
