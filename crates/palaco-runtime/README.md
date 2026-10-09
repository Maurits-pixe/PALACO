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
