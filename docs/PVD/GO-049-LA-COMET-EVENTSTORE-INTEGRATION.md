# ∆ GO-049 — COMET → L.A. EVENTSTORE INTEGRATION

## Objective

Make Authority revocation a persistent part of the L.A. constitutional history.

## Canonical path

RevocationReceipt → canonical_event_payload() → AuthorityRevoked EventEnvelope → PgEventStore::append_revocation() → la.events → reconstruction / verification

## Aggregate identity

AggregateId == AuthorityId
Event.authority_reference == AuthorityId
Event.event_id == RevocationReceipt.revocation_id

This preserves identity across COMET propagation and persistent history.

## Append-only boundary

The integration uses the existing EventStore append contract. It does not update or delete historical events.

Sequence and predecessor hash are obtained from the current aggregate head before the canonical revocation event is appended.

## Cryptographic boundary

The event payload remains exact canonical bytes: payload → SHA-256 → signature.

Persistence reconstructs the exact payload and revalidates its payload hash. Signature validity does not grant authority.

## Constitutional boundaries

- REVOCATION PERSISTS THROUGH EVENTSTORE
- REVOCATION EVENT IS IMMUTABLE
- COMET PRESERVES REVOCATION IDENTITY
- REVOCATION DOES NOT REWRITE HISTORY
- AUTHORITY != AUTHORIZATION
- AUTHORIZATION != EXECUTION
- SIGNATURE != AUTHORITY
- PROVENANCE != PERMISSION

## Verification target

The PostgreSQL integration test verifies canonical AuthorityRevoked event creation, Authority identity binding, persistence through la.events, exact reconstruction, payload-hash integrity, and Ed25519 verification over the exact reconstructed payload.

CI remains the final evidence gate.