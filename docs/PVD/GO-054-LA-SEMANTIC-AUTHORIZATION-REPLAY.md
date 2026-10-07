# GO-054 — L.A. Semantic Authorization Replay & Fail-Closed Reconstruction

**Status:** IMPLEMENTED — CI verification pending  
**Branch:** `go-043-la-execution-gate`

## Purpose

GO-054 advances replay from structural verification to semantic reconstruction of an Authorization aggregate.

The constitutional chain is now:

`AuthorizationIssued → AuthorizationInvalidated → replay → reconstructed Authorization status`

Structural replay remains mandatory before semantic reduction.

## Invariants

1. History MUST pass the existing deterministic replay verifier.
2. The first event MUST be `AuthorizationIssued`.
3. The authorization aggregate identity MUST equal the issued authorization identity.
4. `AuthorizationInvalidated` MUST preserve authorization and authority identity.
5. Unknown authorization lifecycle events MUST fail closed.
6. Reconstruction is state derivation only; it does not create authority.
7. Reconstruction does not create an `ExecutionPermit`.
8. A revoked reconstructed authorization remains non-active and therefore cannot pass the execution gate.

## Constitutional boundaries

- REPLAY ≠ AUTHORIZATION
- RECONSTRUCTION ≠ EXECUTION
- SIGNATURE ≠ AUTHORITY
- PROVENANCE ≠ PERMISSION
- UNKNOWN EVENT ≠ ACCEPTED EVENT
- FAIL-CLOSED > GUESSING

## Verification target

The semantic replay reducer reconstructs:

`AuthorizationIssued(status=Active) → AuthorizationInvalidated(status=Revoked) → Authorization(status=Revoked)`

This establishes a verifiable path from immutable event history to authorization state without introducing mutable authorization state as a source of truth.

## Next hardening gate

GO-055 should close remaining architecture-rule violations in integration-test infrastructure, especially `.expect()` usage, and then re-establish a complete GREEN CI evidence chain before merge.
