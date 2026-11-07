# H∆R∆ / H∆R∆M — reception inbox candidate

**Status: DRAFT / ISOLATED / INTEGRATION HOLD / PRODUCTION HOLD.**

Pure, immutable and dependency-free inbox core for the HARAM message counter when a visitor registers at a Citadel reception. It records a scoped, opaque arrival envelope, deduplicates at-least-once delivery, exposes an exact unread count, and supports explicit READ then HANDLED transitions. No visitor names, VisitCard content, credentials, or raw evidence are copied into notifications.

Run: `node modules/hara/reception-inbox/test.mjs` (Node with ESM support).

## Security boundary

- This module **does not** authenticate operators. The host must verify the PALACO ONE identity, Citadel binding, currently valid capability, revocation, and policy before passing `authorized: true`; that boolean is not an external API security control.
- Never expose this reducer directly as a public HTTP mutation endpoint.
- Persist snapshots and an append-only delivery receipt in a tenant-scoped, access-controlled storage implementation before presenting notifications as durable.
- Device push, subscriptions, realtime transport, offline reconciliation, arrival signing, and audit evidence are **not implemented**.
- Do not equate a reception check-in with approval for admission or access beyond reception.
- Existing Hannie agenda `STORAGE_EFFECT_DEADLINE_UNSUPPORTED` deny remains untouched.

## Acceptance still required

1. Verified reception event source and signed envelope.
2. Authenticated reviewer + Citadel/tenant isolation and revoked-session tests.
3. Atomic persistence, idempotency across restarts, replay protection and offline convergence.
4. Accessible UI indicator and authorized push wake-up, without personal content in push payload.
5. Independent review and evidence before any live activation.

No production integration, schema migration, user access change, merge or approval is performed by this candidate.

## Offline journal candidate

`journal.mjs` reconstructs a Citadel-scoped inbox from ordered append-only entries. It rejects duplicate/no-op entries, sequence gaps and cross-Citadel events, and minimizes stored reception fields. Run `node modules/hara/reception-inbox/journal.test.mjs` alongside the existing tests.

This is a **pure in-memory journal format**, not durable encrypted storage: it does not write to disk, verify cryptographic authenticity, protect against an attacker rewriting a coherent history, or resolve multi-device conflicts. The host must supply authenticated event ingestion, atomic persistence, encryption at rest, external integrity anchors, retention policy and authorization checks before any integration. Restoration is historical reconstruction only and cannot create new authority.

## Single-host atomic storage candidate

`local-store.mjs` provides a Node-only, one-writer file adapter for the offline journal. It uses exclusive lock creation, a write/sync/rename sequence, directory sync and an expected-entry-count check; the prior append-only prefix is checked to reject history rewrites. Run `node modules/hara/reception-inbox/local-store.test.mjs`.

**Limits:** a SHA-256 checksum detects incidental corruption, not malicious rewriting of file and checksum. An attacker able to change the file, a deleted file, a stale lock after a crash, an unsupported filesystem, power-loss behavior, or another machine is outside the demonstrated durability guarantee. Lock cleanup is not automatic after a process crash. This prototype is neither encrypted nor a distributed/production store. Supervised crash recovery, retention, back-up, trusted external anchors and PALACO ONE tenant authorization are pending. No true push delivery has been enabled.

## Write-once backup candidate

`backup.mjs` creates a checkpoint with exclusive file creation and validates its scope, SHA-256 checksum and replayable revision without restoring it. Run `node modules/hara/reception-inbox/backup.test.mjs`. Existing backup files cannot be replaced through this API. A failed interrupted write can leave an incomplete reserved name; recovery requires human inspection.

This checkpoint is **plaintext** and has no independent trust anchor, encryption, key lifecycle, secure deletion, backup rotation, multi-device sync, or automatic restore. SHA-256 alone is not authentication against someone who can rewrite both payload and checksum. Do not put real reception personal data into this isolated candidate. RESTORE / PRODUCTION remain HOLD.
