# Optional RIO/CMV HTTP boundary

This slice builds on storage candidate `d372c151daef4524314fd389f3734d2a72863621`
(draft PR #77). It connects the bounded synthetic PostgreSQL object API to an
explicit same-origin HTTP surface. It does not add an upload UI or modify Citadel.

## Explicit enablement

The default launcher and `router(state)` retain their previous routes. The fixed
loopback development launcher accepts the sole argument `--cmv-storage` to opt
in. A typed caller can instead await `router_with_cmv_storage(state)` after an
existing normal or verified-TLS AppState constructor. This validates the fixed
synthetic browser origin, requires a durable store and installs additive object
schema 0002 before returning any router. There is no memory-storage fallback,
new listener, provider selector, enrollment capability or contact permission.
Restore constructors still commit recovery fences before returning their state.

## Endpoints

| Method and path | Contract |
| --- | --- |
| `POST /api/storage/objects` | Strict JSON object with `objectId`, `payload`, `retentionMs`; immutable create, returns 201 after commit with ID, SHA-256 and byte count. |
| `GET /api/storage/objects/{objectId}` | Own live object only; returns verified opaque bytes and SHA-256 as base64url in JSON. |
| `DELETE /api/storage/objects/{objectId}` | Strict empty JSON object `{}`; clear live bytes with retained tombstone/audit. |
| `GET /api/storage/usage` | Own live-byte and retained-slot usage, plus explicit limits. |

All access uses the existing opaque HttpOnly session cookie. No account/tenant
selector, provider credential, filesystem path or external storage URL is
accepted. IDs encode exactly 32 bytes and payloads encode 1–16384 bytes with
canonical unpadded base64url. Retention remains 1 ms to 24 hours. Unknown and
duplicate JSON fields, JSON arrays, invalid UTF-8, noncanonical encoding and
coerced field types are rejected. The create route alone has a 24000-byte body
budget; consent, logout and delete retain their existing 256-byte budget.

Writes reuse the exact browser origin, JSON content type and unique CSRF-header
requirements and revalidate CSRF against the current database session in the
same transaction as the mutation. Host/HTTP2 authority, duplicate cookie/header,
query-selector, forwarded-header and bearer rejection still wrap every route.
No CORS permission is added. Responses retain no-store, CSP and nosniff headers;
opaque payload is JSON data and never served as active browser content.

Quota/conflict/revocation/unavailability use the existing 429/409/401/503
categories; missing, foreign and terminal objects all return 403. Generic error
responses do not disclose raw database, provider or payload diagnostics. The
existing storage limits, lazy expiry, lifetime tombstones and append-only object
audit from CMV-STORAGE-SLICE.md apply without change. Returned envelopes retain
SYNTHETIC_ONLY, inactive accounts, no contact capability and no operative authority.

## Evidence requirements

The unit router contract covers strict input, route-specific body budgets,
default-off behavior, origin/CSRF/header denial and absent-database failure.
`fixture.py run-storage-tests` explicitly runs the actual PostgreSQL HTTP contract
in addition to the storage contracts, covering full-size bytes, cross-account
read/delete denial, conflicting IDs, quota, expiry, deletion and revocation.
The existing verified-TLS service contract also invokes the optional routes.

The owned TLS OIDC harness explicitly selects this router and fixes
`RIO_CMV_HTTP_PROOF=1` after stripping inherited test selectors. Under that fixed
test flag, RIO-E2E-01 must exercise object create/read/delete, peer CSRF denial,
foreign-object denial, immutable IDs and quota access after real Keycloak login.
The phase runs both against primary TLS storage and the fenced restored TLS
clone. The default launcher/browser suite does not select this optional mode.

This candidate is reviewable code and test work only. It authorizes no merge,
deployment, live personal data, production migration or public account activation.
