# RIO T05 — bounded incident-evidence triage

### Status
DRAFT · SYNTHETIC_ONLY · READ-ONLY TRIAGE · NO ROOT-CAUSE DETERMINATION · HUMAN ACCEPTANCE HOLD

### Last Updated
2026-10-15

## Purpose and evidence
The original natural Android `RIO-MOBILE-01` post-consent failure in [CI #38587411896](https://github.com/Maurits-pixe/PALACO/actions/runs/38587411896) did not contain its actual divergent HTTP status. It cannot be reconstructed. The later [PR #62](https://github.com/Maurits-pixe/PALACO/pull/62) injected 401 and `connectionreset` and verified that both yield strict failure-only evidence with no retries (15/15 browser tests PASS). These are **controlled symptoms**, not a known cause for the historical natural error.

## Read-only categorization contract
`verification/rio-accounts/post-consent-triage.mjs` consumes only a previously validated `rio-mobile-post-consent-read` annotation via the strict existing `safePostConsentObservation` validator. It does not listen to live sessions, read hidden cookies or make HTTP/database requests.

| Observed bounded symptom | Display-only classification | Human investigation prompt |
| --- | --- | --- |
| Browser's account request failed (status null) | `TRANSPORT_FAILURE` | Examine sanitized browser/network event ordering |
| Actual response 401/403 | `ACCESS_DENIED` | Examine account binding, epoch, revocation and cookie scope with independent evidence |
| Actual response 5xx | `SERVER_RESPONSE_ERROR` | Examine BFF/database/IdP boundaries with independent evidence |
| Actual response 3xx | `UNEXPECTED_REDIRECT` | Examine authentication route/redirect sequence |
| Other non-200 integer response | `HTTP_UNEXPECTED` | Examine session binding and server response |
| Absent, duplicated, malformed, sensitive or forged record | `EVIDENCE_UNUSABLE` | Hold; retain original private evidence only in owner-controlled storage |

Every returned object **always** declares `rootCause=UNKNOWN`, `decision=HOLD`; it never grants authority, verifies identities, initiates an action, guesses a remediation or reads a private event. The allowed observation copy has only fixed enumerated fields, numeric synthetic consent revisions, account-status integer/null, request-failed Boolean, cookie **presence** Boolean/null and a whitelisted error-kind label. No bearer values, URL parameters, session tokens, credentials, account identity, raw response, network addresses or original exceptions.

The associated Node tests require strict HTTP symptom categorization and HOLD across all cookie-presence and consent-revision combinations. Secret-bearing, missing, duplicate and inconsistent records must yield `EVIDENCE_UNUSABLE / HOLD`. GO-13 and complete exact-head RIO/TLS/browser CI must be independently verified.

## Governance and next evidence
The initial triage head `bc4842d41e4d4f4830b7ade136e02c28b39b859b` passed [GO-13 #38598680032](https://github.com/Maurits-pixe/PALACO/actions/runs/38598680032), but [RIO #38598680026](https://github.com/Maurits-pixe/PALACO/actions/runs/38598680026) FAILED at the second BFF restart with protected `/proc` environment access denied. Source checks, Rust 42 regular tests plus three additional checks, actual PostgreSQL TLS/binding, storage, consent, real OIDC browser and actor-scoped revocation passed before that failure. Subsequent mobile, durable-denial and backup/restore steps were skipped; they are not PASS on that head.

The continuation ports only the fixture ownership hardening and three regression tests from draft #63, then adds a fourth test exercising `stop_bff` through a reused PID. Generation mismatch must be rejected before protected process reads or pidfd acquisition; inaccessible ownership remains a fixed secret-free error with metadata retained. This is test-harness hardening, not proof that PID reuse caused the historical permission error (#64). No runtime service, database, TLS, timeout, retry or account policy changes. Local mocked checks cannot prove Linux `/proc` behavior; complete exact-head Linux RIO and GO-13 remain required.

A future *natural* failure with an accepted diagnosis-free record can orient manual investigation, but **classification ≠ causation**. Reproducing a real product defect requires an independently supported chain of evidence and cause-specific regression. The historical first failure will not be relabeled.

This is a separate stacked DRAFT atop [PR #62](https://github.com/Maurits-pixe/PALACO/pull/62), not a publication, deployment, merge, account migration or runtime connector. [Issue #60](https://github.com/Maurits-pixe/PALACO/issues/60) and separate pre-login [issue #51](https://github.com/Maurits-pixe/PALACO/issues/51) remain OPEN. T04 independent human acceptance [#50](https://github.com/Maurits-pixe/PALACO/issues/50), real identities, ACCOUNT-1, physical devices, NOVA contact, staging and production remain HOLD.
