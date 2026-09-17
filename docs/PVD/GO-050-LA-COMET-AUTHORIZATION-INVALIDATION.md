# GO-050 — COMET Propagation → Authorization Invalidation

**Status:** IMPLEMENTED — source boundary established  
**Branch:** `go-043-la-execution-gate`

## Constitutional objective

Authority revocation shall not stop at the authority object. It shall propagate to every authorization explicitly bound to that authority.

> **AUTHORITY REVOCATION => AUTHORIZATION INVALIDATION**

## Propagation chain

`RevocationReceipt` → COMET identity match → `AuthorizationInvalidation` → revoked authorization state → execution lifecycle STOP.

The binding is explicit:

- `Authorization.authority_id == RevocationReceipt.authority_id`
- mismatched authority identity blocks propagation
- invalidation preserves `revocation_id`
- invalidated authorization cannot create a new `ExecutionPermit`
- an already-issued permit is still stopped by lifecycle evaluation against the invalidated authorization
- authority revocation remains distinct from authorization invalidation

## Non-negotiable boundaries

- ACCESS ≠ AUTHORIZATION
- AUTHORITY ≠ AUTHORIZATION
- AUTHORIZATION ≠ EXECUTION
- SIGNATURE ≠ AUTHORITY
- PROVENANCE ≠ PERMISSION
- REVOCATION DOES NOT REWRITE HISTORY
- COMET DOES NOT CREATE AUTHORITY
- COMET DOES NOT EXPAND SCOPE
- UNKNOWN / inactive authorization => FAIL CLOSED

## Implementation

### Domain
Added `AuthorizationStatus`:

- Active
- Suspended
- Revoked
- Expired
- Superseded

New authorizations are explicitly created as `Active`.

### COMET
`comet.rs` introduces:

- `AuthorizationInvalidation`
- `CometError::AuthorityMismatch`
- `propagate_revocation()`
- `apply_invalidation()`

The invalidation is represented as a new state value; the prior event history remains immutable.

### Execution gate
The execution gate now rejects any authorization whose status is not `Active`.

### Execution lifecycle
The lifecycle checks:

1. authorization ↔ authority identity
2. permit ↔ authorization identity
3. authorization status
4. authority status

A revoked authorization therefore produces:

`STOP / AuthorizationRevoked`

## Scope

GO-050 establishes the operational propagation boundary. Persistent authorization lifecycle events/projections and bulk reconstruction across all authorizations remain a subsequent persistence concern.

## Verification targets

- matching authority propagates
- mismatched authority is blocked
- invalidation preserves revocation identity
- revoked authorization cannot mint a new execution permit
- previously issued permit cannot bypass lifecycle stop
- constitutional architecture rules explicitly encode the COMET boundary
