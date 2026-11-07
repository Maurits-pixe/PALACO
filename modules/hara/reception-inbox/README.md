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
