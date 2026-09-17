# GO-051 — Persistent AuthorizationInvalidation Event

**Status:** IMPLEMENTED

## Objective

GO-050 established the operational COMET boundary. GO-051 makes authorization invalidation itself a first-class immutable L.A. event.

## Canonical chain

AuthorityRevoked -> RevocationReceipt -> COMET identity match -> AuthorizationInvalidation -> AuthorizationInvalidated -> PostgreSQL la.events -> exact reconstruction -> execution lifecycle STOP.

## Event contract

Event type: AuthorizationInvalidated.

Aggregate identity: AggregateId == AuthorizationId.

Identity bindings:
- event.event_id == propagation_id
- event.authority_reference == AuthorityId
- payload contains revocation_id
- payload contains authorization_id
- payload contains AuthorizationStatus::Revoked

The event payload is converted to CanonicalBytes, hashed, and signed over the exact bytes. Persistence reconstructs those exact bytes and revalidates the payload hash.

## Constitutional guarantees

- REVOCATION DOES NOT REWRITE HISTORY
- AUTHORIZATION INVALIDATION IS NEW HISTORY
- COMET DOES NOT CREATE AUTHORITY
- COMET DOES NOT EXPAND SCOPE
- AUTHORITY IDENTITY MUST MATCH
- INVALIDATED AUTHORIZATION CANNOT CREATE A NEW EXECUTION PERMIT
- INVALIDATED AUTHORIZATION FORCES EXECUTION LIFECYCLE STOP
- SIGNATURE != AUTHORITY
- PROVENANCE != PERMISSION

## Persistence boundary

PgEventStore::append_authorization_invalidation() uses the existing append-only EventStore boundary. The la.events history remains immutable; aggregate-head locking supplies the existing concurrency control.

## Verification

The PostgreSQL integration test verifies canonical event persistence, Authorization aggregate identity, Authority identity reference, propagation identity, exact reconstruction, SHA-256 payload integrity, and Ed25519 signature verification.

Bulk authorization discovery/projection across all historical authorization records remains a subsequent query/projection layer. GO-051 deliberately does not introduce a mutable authorization table that could bypass L.A. event history.
