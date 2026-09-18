# GO-056 — L.A. Replay-to-Execution Negative Path

**Status:** IMPLEMENTED — CI verification pending

## Purpose

GO-056 closes the constitutional negative path between persistent authorization history and the execution gate.

The required chain is:

```text
AuthorizationIssued
    ↓
AuthorityRevoked
    ↓
COMET propagation
    ↓
AuthorizationInvalidated
    ↓
PostgreSQL reconstruction
    ↓
Structural replay verification
    ↓
Semantic authorization replay
    ↓
AuthorizationStatus::Revoked
    ↓
ExecutionGate rejection
    ↓
NO ExecutionPermit
```

## Invariants

1. Authorization is reconstructed from immutable event history.
2. Structural replay verifies genesis, aggregate continuity, sequence continuity, predecessor hash, payload digest and signature.
3. Semantic replay requires successful structural replay.
4. COMET preserves the authority and authorization identities.
5. A replayed revoked authorization remains revoked.
6. The execution gate rejects every non-active authorization.
7. A revoked replay therefore cannot produce an `ExecutionPermit`.
8. No panic-driven integration-test infrastructure is introduced; failures propagate through `Result`.

## Constitutional boundaries

- REPLAY != AUTHORIZATION
- RECONSTRUCTION != EXECUTION
- SIGNATURE != AUTHORITY
- PROVENANCE != PERMISSION
- REVOCATION => STOP
- REPLAYED REVOKED AUTHORIZATION => EXECUTION GATE REJECTS

## Evidence target

The PostgreSQL integration test `postgres_replay_of_revoked_authorization_cannot_create_execution_permit` is the executable evidence target for this gate.

CI GREEN remains unclaimed until GitHub Actions verifies the current branch head.
