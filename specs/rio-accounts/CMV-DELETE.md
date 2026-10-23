# Verified conditional deletion and terminal confirmation

This candidate builds on draft PR #80, exact base
`58a3665e93c5f5a321561527e3b25f7080e6b25c`. The optional synthetic CMV API
accepts `DELETE /api/storage/objects/{objectId}` with a strict JSON object
containing `sha256`, the canonical unpadded base64url encoding of the expected
32-byte digest. The existing empty object request keeps its live-only behavior.
An explicit null, duplicate digest, unknown field or noncanonical value is
rejected; the existing 256-byte DELETE body limit remains in force.

The stored session supplies account and tenant. A valid cookie, exact origin,
CSRF and the existing revocation guard are required for both deletion and its
confirmation. The transaction first expires due content and validates the
complete bounded account catalog: live hashes, creation audit, retained slots,
usage and attributable terminal events. A wrong expected digest returns 409
without deleting content; missing and foreign IDs share the existing 403.

A matching live object is atomically cleared, marked DELETED and given its one
terminal audit event. A matching DELETED or EXPIRED object is confirmed without
another event. The 200 response contains the actual state, retained digest,
original `endedAt`, `liveBytes: 0`, `payloadVerified: false`, and verified account
usage after the operation. Expiry is reported as EXPIRED, never relabelled as
user deletion. A retained digest does not claim that erased bytes remain
available for verification. The original ID, deadline and audit stay retained.
Usage may reflect other committed account changes between separate requests;
each receipt's usage is consistent with its own transaction.

Independent deletion requests serialize under the same guard. A lost response
can be retried on a healthy connection or after fresh bound authentication,
without clearing another object's bytes or appending a duplicate audit event.
An audit insert failure rolls back both byte clearing and the state transition
and poisons that store handle. Revoked, expired or pre-restore sessions never
receive a receipt, even when the requested object is already terminal.

The same complete catalog validation now precedes single-object reads,
create-only POST, legacy DELETE and quota reporting. Previously a payload hash
alone was sufficient for a single-object read, while quota reporting used an
unchecked aggregate. Valid bytes with inconsistent creation audit must now
close these paths too. No route releases content, acknowledges mutation or
reports usable capacity from a corrupt account catalog. This validation cannot
authenticate a privileged operator capable of replacing both data and audit.

The owned PostgreSQL deletion contract runs after catalog verification and
before the retry contract. It checks concurrent deletion, stable terminal time
and event counts, account/CSRF separation, wrong-digest preservation, expiry,
full lifetime slots, audit failure atomicity, six operations against two
injected integrity faults, fresh login and recovery fencing. Only its owned
injected object row is repaired; append-only audit is never altered or erased.
HTTP tests cover strict nullable/duplicate/type handling and terminal receipts.
The mandatory real-provider browser phase checks conditional deletion and
confirmation on primary and restored TLS storage.
Native TLS pg_dump/pg_restore additionally carries a known deleted marker with
its two audit events; a fresh bound session confirms its original terminal time
after restore while the pre-restore session remains denied.

Limits remain 16 KiB/object, 64 KiB live bytes/account, 64 lifetime retained slots
and at most 24 hours retention. Physical expiry remains lazy. Byte clearing
does not claim erasure from WAL or backups. No schema migration or Citadel
change is required. Routes remain default-off and synthetic-only; provider/user/
account binding, TLS, revocation and append-only audit stay in force. No merge,
deployment, personal-account activation or contact permission is performed.
