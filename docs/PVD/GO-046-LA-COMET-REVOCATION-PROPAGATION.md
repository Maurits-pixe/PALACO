# ∆ GO-046 → GO-047 — L.A. COMET REVOCATION PROPAGATION

## Constitutional rule

REVOKE is a first-class lifecycle event. Revocation does not erase historical events, receipts or provenance.

## COMET boundary

REVOKE → DETECT → PROPAGATE → BLOCK / REASSESS → RECEIPT → PRESERVE PROVENANCE

GO-046 introduces explicit revocation and propagation receipts. GO-047 binds the revocation to a canonical immutable L.A. EventEnvelope and signs the exact canonical payload. A propagation receipt binds a revocation event to a target execution and records an explicit propagation status.

## Rules

- REVOKE => PROPAGATE
- REVOCATION PRESERVES PROVENANCE
- REVOCATION DOES NOT REWRITE HISTORY
- PROPAGATION STATUS IS EXPLICIT
- REVOKED AUTHORITY => STOP
- EXPIRED AUTHORITY => STOP
- SUSPENDED AUTHORITY => REASSESS

## Non-goals

GO-046 does not execute side effects, delete historical events, or infer authority from the existence of a valid cryptographic signature. It also does not make RIO an authority mechanism.

## GO-047 EventStore boundary

A revocation is represented as an immutable `AuthorityRevoked` event with the authority reference, event identity, payload hash, provenance and exact-byte signature. The event is suitable for append-only persistence through the existing EventStore boundary; this step does not yet add a special persistence shortcut or allow historical mutation.

## Verification

Source implementation is present. GitHub Actions remains the authoritative compile/test/Clippy gate; the branch is not claimed GREEN until an actual run succeeds.
