# Immutable upload retries

This candidate builds on draft PR #79, exact base
`0cf144d16722261d68720211743fec24e7354eb4`. The optional synthetic CMV API
adds `PUT /api/storage/objects/{objectId}` with a JSON object containing only
`payload` (canonical unpadded base64url) and `retentionMs` (an integer).
Clients choose and retain their opaque 32-byte ID before the first request.

A new object returns 201. An identical request for an existing live object
returns 200 only after validating its exact bytes, SHA-256, creation audit,
original retention duration and the complete bounded account catalog. The
response uses the existing closed object envelope and contains the ID, digest
and byte count. An unknown prior network outcome may therefore be retried on a
fresh healthy connection without adding a slot or a duplicate audit event.
No in-process cache is authoritative.

The stored session supplies account and tenant. Authentication, CSRF, lazy
expiry, integrity checks, quota decisions and any creation share the existing
revocation guard and transaction. Independent connections serialize: exactly
one matching writer creates an object, while the other confirms it. A matching
retry needs no additional bytes or slots, even at either account limit.
The original creation timestamp and deadline never move. The session's existing
idle/absolute limits remain applicable; this API grants no extra session life.

Different bytes or a different original retention duration return 409.
Deleted or expired IDs also return 409; the API never resurrects them.
Object IDs are scoped to the bound account, so another account cannot confirm,
overwrite or inspect its peer's object by choosing the same ID. It can create
its own independent object under that ID, subject to its own quotas.
The original POST collection endpoint remains create-only and returns 409 for
an existing ID. Neither endpoint changes the lifetime tombstone policy.

Only PUT receives the existing 24,000-byte upload body budget on the object
path. DELETE retains its 256-byte limit. Unknown/duplicate fields, array-shaped
JSON, noncanonical base64url, empty/oversize content, query selectors and
malformed IDs fail closed. Existing exact Host/origin, cookie-only access,
CSRF, no-store/CSP/no-CORS headers and fixed synthetic origin remain in force.
Corrupt bytes or unattributable lifecycle audit return unavailable and poison
the store handle, with no partial acknowledgement. There is no new migration.

The owned PostgreSQL retry contract runs explicitly after the existing catalog
contract. It covers concurrent same/different writes, reconnect retries,
unchanged deadlines/usage/audit, account separation, byte and lifetime quotas,
terminal IDs, atomic audit failure, corruption, revocation and recovery fencing.
The real-provider browser phase creates and reconfirms an upload on both primary
and restored TLS storage. HTTP tests retain strict input and method body limits.

Scope remains synthetic and default-off: 16 KiB/object, 64 KiB live bytes/account,
64 lifetime retained slots and at most 24 hours retention. Provider/user/account
binding, TLS, revocation and append-only audit are preserved. No personal-account
activation, contact permission, merge or deployment is performed.
