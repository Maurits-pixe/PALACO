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

## Supervised recovery inspection candidate

`recovery.mjs` inspects the single-host store and optional backup **without mutations**. It returns `HOLD_FOR_HUMAN_RECOVERY` on missing/invalid store, lock files, detected temporary write remnants, invalid/newer backups or same-revision content divergence. Run `node modules/hara/reception-inbox/recovery.test.mjs`. No deletion, lock takeover, rollback, restore or authorization is implemented.

**Limitations:** filesystem scans are not atomic with concurrent writes; checksum comparisons do not prove trusted identity or time; older backup histories are not cryptographically anchored; a deleted store cannot be distinguished from a clean first install without an external anchor. Operators must stop writers and use separately approved recovery procedures. No live production use.

## Multi-device synchronization preflight (read-only)

`sync-contract.mjs` compares two validated same-Citadel journals using distinct device labels. It classifies equal history, one device behind, or first divergent entry (`CONFLICT_HOLD`). Run `node modules/hara/reception-inbox/sync-contract.test.mjs`. It never transmits data, combines histories, changes a local store, or grants authority. A behind-device verdict is **not** permission to replicate.

Device labels are unverified input, not PALACO ONE identity. JSON bytewise equality is conservative and can flag semantically equal entries with different property ordering; that is a safe false HOLD. Authentic signatures, canonical serialization, revocation, trusted sequence anchors, anti-rollback, encrypted transport, authorization and human conflict resolution remain OPEN. No automatic merge or production synchronization.

## Signed sync manifest candidate

`signed-manifest.mjs` signs a short-lived, Citadel- and device-labeled SHA-256 journal summary with a caller-supplied Ed25519 private key. The verifier checks a caller-supplied public key, target, journal revision/content, time window (maximum 300 seconds) and signature. Run `node modules/hara/reception-inbox/signed-manifest.test.mjs`.

**Critical boundaries:** public keys are not bound to a trusted PALACO ONE device identity; callers choose their own time; nonce use is not persistently recorded and therefore replay protection is **NOT established**. The signature does not encrypt journal content, transmit payloads, establish recipient authorization or prove trustworthy clock time. No real keys or user content are stored in this module. Trust anchors, key rotation/revocation, durable nonce registry, encryption and authorized transport must be separately verified. This is not a production handshake.

## Pinned-key and nonce trust gate candidate

`trust-gate.mjs` compares a signed manifest against an externally supplied, Citadel-scoped, unique, non-revoked public-key record and an externally supplied consumed-nonce snapshot. It returns an immutable proposed nonce reservation without executing any transfer. Run `node modules/hara/reception-inbox/trust-gate.test.mjs`.

**Not a live authority gate:** this module cannot establish that the pinned record belongs to a real PALACO ONE device, validate who provisioned or revoked it, or atomically persist the nonce. The host must durably commit the nonce reservation and use a trusted clock before releasing anything; otherwise replay remains possible. The module returns `authorityGranted: false` even when a signature passes. No enrollment, remote execution, key rotation, storage migration, transmission or deployment has occurred.
