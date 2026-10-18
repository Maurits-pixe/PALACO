# Account-owned CMV catalog and recovery proof

This candidate builds on `fdc9bb2f11bea2ad0f6a5cb4f47b42bdf3662ae9`
(draft PR #78). The optional storage API gains `GET /api/storage/objects` so a
freshly authenticated account can recover its object IDs after losing client
memory. No browser storage, new UI, external provider or Citadel change is added.
Default-off behavior, the fixed synthetic origin, TLS configuration and provider
issuer/subject/account binding remain unchanged.

## Snapshot contract

The stored session supplies account and tenant; callers cannot choose an owner.
The existing guard lock serializes expiry, revocation and storage mutations.
A single SQL statement reads objects and their lifecycle audit from one snapshot.
The result includes every retained slot, in ascending opaque-ID byte order,
plus usage computed from those exact entries and the database observation time.
The 64-slot limit permits a complete response without paging. A 65th row or
over-budget payload total is an integrity failure, never a truncated success.

Every entry has `objectId`, `sha256`, `state`, `liveBytes`, `createdAt`,
`expiresAt`, `endedAt`, and `payloadVerified`. Payload bytes, owner/tenant IDs,
credentials and arbitrary user text are absent. Root envelopes retain the
existing closed authority fields and use `RIO_CMV_SYNTHETIC_CATALOG_V1`.
HTTP access retains no-store, CSP, nosniff, no CORS and generic closed errors.

Before any metadata is returned, the store validates each live payload's SHA-256,
the creation event/time, retention bounds and terminal-event consistency. Live
entries have no terminal event. Deleted/expired entries have empty payloads and
a matching attributable terminal event; expiry cannot precede its deadline.
`payloadVerified` is true only for live bytes verified during this snapshot.
For tombstones, SHA-256 is a retained reference, not proof that erased content
is still available. A corrupt entry closes the whole catalog and poisons that
connection. No partial metadata result is released.

Lazy expiry can clear expired bytes and append their terminal events inside the
catalog transaction. A read without new expiry adds no events or slots. A fresh
login can recover surviving objects; old revoked or restored sessions cannot.
The catalog does not reactivate sessions, renew consent, extend sessions or
change contact authority. It also does not authenticate a privileged operator
who can replace both objects and audit, and guarantees no erasure from WAL or
backups. Existing lifetime tombstone and retention policies still apply.

## Verification

The owned PostgreSQL catalog contract is selected explicitly by
`fixture.py run-storage-tests`, after the existing storage and HTTP contracts.
It checks stable ordering, accurate snapshot usage, cross-account isolation,
reconnect discovery, live/deleted/expired metadata, all 64 retained slots,
independent-client writes, corruption and missing lifecycle audit, revocation,
recovery fencing and fresh account access. Injected faults are repaired only
inside the owned disposable fixture; append-only events are never erased.

The actual HTTP contract checks collection authentication, absence of payload
and owner fields, isolation and revocation. The mandatory real Keycloak browser
phase checks own/foreign catalogs and deletion metadata on primary and restored
TLS storage. Native TLS dump/restore now compares complete CMV object/event rows
and carries a live marker object through real pg_dump/pg_restore: stale sessions
stay denied, while fresh authentication recovers its catalog and verified bytes.

No merge, deployment, live migration, personal-account activation or new contact
permission is authorized by this candidate.
