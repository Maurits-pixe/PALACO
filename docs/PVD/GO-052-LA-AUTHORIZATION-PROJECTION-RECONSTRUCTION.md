# GO-052 — L.A. Authorization Projection / Reconstruction

**Status:** IMPLEMENTED — verification pending CI

## Constitutional objective

GO-052 makes authorization lifecycle state reconstructible from immutable L.A. event history.

The system does **not** introduce a mutable authority table or mutable authorization source of truth.

Canonical chain:

`AuthorizationIssued` → immutable `la.events` history → deterministic active-authorization reconstruction → COMET fan-out → individual `AuthorizationInvalidated` events.

## Authorization issuance

Each authorization is represented by a canonical `AuthorizationIssued` event.

- aggregate identity = AuthorizationId
- authority reference = AuthorityId
- event identity = AuthorizationId
- payload contains authorization identity, decision identity, authority identity, scope and lifecycle status
- signature covers the exact canonical payload bytes
- event history remains append-only

## Deterministic reconstruction

For a given AuthorityId, the PostgreSQL reconstruction query selects the latest event for each Authorization aggregate bound to that authority.

An authorization is considered active for COMET discovery only when its latest lifecycle event is `AuthorizationIssued`.

An authorization whose latest event is `AuthorizationInvalidated` is therefore excluded without mutable-state mutation.

## COMET collective invalidation

Authority revocation can now deterministically discover all currently active authorizations bound to that Authority.

For every discovered AuthorizationId, COMET emits a separate `AuthorizationInvalidated` event carrying:

- revocation identity
- authority identity
- authorization identity
- explicit Revoked status
- observation time

Each invalidation is persisted through the existing append-only EventStore.

## Constitutional boundaries

- AUTHORITY != AUTHORIZATION
- AUTHORIZATION != EXECUTION
- ACCESS != AUTHORIZATION
- REVOCATION does not rewrite history
- derived reconstruction is not authority
- a projection cannot grant permission
- COMET invalidates; it does not create authority
- individual invalidation events preserve provenance and replayability

## Verification target

GO-052 is complete only when CI verifies:

1. authorization issuance persistence;
2. deterministic active-authorization reconstruction;
3. two or more active authorizations bound to one authority are all discovered;
4. authority revocation creates one immutable invalidation event per active authorization;
5. reconstruction returns no active authorizations after invalidation;
6. existing Rust, PostgreSQL, cryptographic and architectural gates remain green.

**CI GREEN is not claimed until GitHub Actions confirms the complete workflow.**
