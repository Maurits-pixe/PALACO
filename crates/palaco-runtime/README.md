# ELIXER runtime kernel v0.1

`elixer` implements a deterministic synthetic H∆R∆ candidate in `palaco-runtime`.
It parses a strict, versioned manifest, binds the request to its exact package
digest and tenant/world/Citadel context, checks policy, consent, expiry and a
version-bound revocation record, and rejects stale inputs against the policy
freshness window. It then returns typed state, adapter proposals and a
digest-bound trace receipt.

This is not an identity verifier, proof/signature verifier, manifest issuer,
authorization service or production-data integration. The `verified` identity
fixture flag and supplied provenance/revocation/policy records are assertions
for synthetic tests; provenance and authorization references remain explicitly
unverified. The deterministic H∆R∆M, Ching Ching and Hannie adapters perform
no IO. Even an execution request with an authorization reference remains
`ExecutionPendingAuthorization`; there is no execution commit path.

The runtime result is canonical. `bind_surface` creates a surface reference to
the same receipt digest and does not maintain a separate state. Conformance
passing does not activate the candidate. `TraceWriter` retains validated
results append-only in memory for the lifetime of the process; durable storage
and independent release review remain outside this MVP.

## 6RI9ADE reference gate

`sixri9ade` is an executable, synthetic-only reference evaluator for the
PALACO-Citadel 6RI9ADE concept. It requires nine signed specialty results for
each side (18 total), a sender initiation, a separately signed receiver
NOVA-admission receipt, and distinct sender/receiver final-consent receipts
bound to the same request, admission, and complete evidence-set digest.

The evaluator checks Ed25519 signatures against an explicitly host-supplied
trust snapshot, request/context binding, freshness, bounded validity, and
revocations. Missing evidence and stale trust return HOLD/pending; invalid,
expired, or revoked evidence never passes. A passing reference result still
sets `canOpenContact=false`, `operativeAuthority=NONE`, and
`externalSideEffect=false`. The returned trace digest is not durable storage.

This Rust binding is not a production service or a claim of wire-level
conformance with the separate concept PR. In particular, it cannot authenticate
the host-supplied trust snapshot and is not connected to real accounts, NOVA,
E2EE, bodyguard services, message delivery, a RIO surface, or external
execution. All test keys and examples are synthetic. Passing tests do not
activate or authorize anything.
