# RIO/CMV bounded storage slice

This candidate adds actual PostgreSQL object persistence through an internal
`PgStore` API. It builds on `1121f4950e1d39df0ac33d28d0abf3b620478df0`, including
verified TLS, exact provider issuer/subject binding, closed bootstrap validation,
revocation and restore fencing. It does not activate accounts or contact rights.

## Operator boundary

`initialize_cmv_storage()` explicitly installs additive migration 0002 after
validating the existing synthetic bootstrap. Existing service constructors and
HTTP routes do not automatically enable it. This first slice is for synthetic
fixtures only, with the two existing actors. No Citadel browser storage, provider
configuration, TLS policy or enrollment behavior changes. CMV here names the
bounded opaque-object substrate, not a new external CMV protocol or authority.

## Contract

* `put_cmv_object`: immutable opaque ID, 1–16384 payload bytes, retention from
  1 ms to 24 hours. Computes and returns SHA-256; duplicate IDs cannot overwrite
  content, including after deletion/expiry. No caller-supplied account or tenant.
* `read_cmv_object`: current session/epoch and tenant predicates, deny expired
  and terminal objects, verify stored SHA-256 before returning bytes. Missing
  and foreign IDs have the same error. Digest mismatch closes the connection.
* `delete_cmv_object`: same authenticated ownership plus CSRF. Clears live bytes
  atomically with a terminal event; retained ID/digest prevents resurrection.
* `cmv_usage`: reports the authenticated account's usage and sweeps its expired
  payloads. Expiry is lazy: bytes can remain physically stored until that account
  accesses storage, but are never returned after expiry. No background worker.

The existing database guard lock serializes quota decisions across connections
with session validation, account revocation and recovery. Each account has a
64 KiB live payload budget and 64 **lifetime** object slots. Tombstones keep their
slot; deletion/expiry release bytes, not slots. This deliberately bounded first
slice requires a separate future retention/compaction policy before expansion.
The absolute/idle session deadlines retain their existing semantics; storage
operations do not extend them. Reauthentication to the same account can access
that account's surviving objects. Revocation closes old sessions, not ownership.

## Audit and integrity

`cmv_events` stores one creation and at most one terminal event per object in
the same transaction as the payload change. This bounds object audit at 128
events per account, independently of the existing session audit saturation
budget. Update, delete and truncate are rejected by an immutable audit trigger.
The original session audit and disabled outbox remain unchanged. Object events
do not dispatch an external side effect. No object payload, credential, filename
or arbitrary user-provided text enters audit. SHA-256 detects accidental payload
corruption; it does not authenticate a privileged operator changing both payload
and digest. Physical erasure from PostgreSQL backups/WAL is outside this slice.

## Verification

`cargo test --manifest-path services/rio-accounts/Cargo.toml --locked` runs input
boundary and existing OIDC/TLS configuration tests. The ignored
`postgres_cmv_storage_contract` must actually run against the owned disposable
PostgreSQL fixture; `fixture.py run-storage-tests` now selects it explicitly.
It requires a fresh CMV fixture, preserves its append-only records, and checks:

* CSRF denial without allocation, tenant isolation, immutable IDs;
* independent-connection quota competition and retained slots;
* reconnect durability, deletion and expiry with attributable events;
* update/delete/truncate denial for object audit;
* revocation, recovery fencing, fresh account access;
* injected audit-write failure rolling back object creation;
* corrupt bytes denied before release and poisoned connection health.

The existing actual PostgreSQL TLS contract also creates, reads and deletes a
CMV object over its verified TLS connection. CI keeps the original native
backup/restore and real-provider/browser checks. A passing unit suite alone is
not evidence that these ignored database or browser checks executed.

No merge, deployment, remote provisioning or production migration is performed
by this slice. The draft PR is stacked on the existing RIO candidate branch.
