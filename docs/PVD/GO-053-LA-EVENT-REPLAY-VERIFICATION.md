# GO-053 — L.A. Event Replay & Reconstruction Verification

**Status:** IMPLEMENTED — CI verification pending.

## Objective

GO-053 establishes an explicit replay-verification boundary for the immutable L.A. event history.

A reconstructed history is not accepted merely because rows can be read from PostgreSQL. The complete chain must remain internally coherent and cryptographically verifiable.

## Replay invariants

For an event history:

1. the history must be non-empty;
2. the first event must be genesis;
3. every event must retain the same aggregate identity;
4. sequence numbers must advance exactly by one;
5. each predecessor hash must equal the previous event payload hash;
6. each payload hash must equal the SHA-256 digest of its exact bytes;
7. every signature must verify against those exact payload bytes.

Failure of any invariant fails replay.

## Constitutional meaning

Replay is verification, not authority.

`verify_history()` does not create authorization, alter lifecycle state, or grant execution permission.

It establishes that the persisted event history can be reconstructed without violating its cryptographic and structural invariants.

Therefore:

**SIGNATURE != AUTHORITY**

**REPLAY != AUTHORIZATION**

**RECONSTRUCTION != EXECUTION**

## Adversarial coverage

The replay module includes tests for:

- valid history;
- payload tampering;
- broken predecessor linkage.

These tests operate on the exact event bytes and verify failure at the earliest violated invariant.

## GO-053 acceptance gate

CI must verify:

- unit tests;
- PostgreSQL integration tests;
- formatting;
- compilation;
- Clippy;
- existing architecture gates.

CI GREEN is not claimed until the workflow completes successfully.
