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

`sixri9ade` is an executable, synthetic-only reference evaluator informed by
the [PALACO-Citadel 6RI9ADE concept PR #35](https://github.com/Maurits-pixe/PALACO-Citadel/pull/35).
It requires nine signed specialty results for
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
execution. Callers must supply a trusted clock and independently reload both
snapshots; the evaluator itself cannot establish either trust boundary. All test
keys and examples are synthetic. Passing tests do not activate or authorize
anything.

### Run the reference evaluator

The Rust CLI reads one strict JSON bundle from standard input and writes one
JSON result to standard output:

```sh
cargo run -p palaco-runtime --bin sixri9ade < bundle.json
```

The bundle uses schema `elixer-6ri9ade-bundle-v0.1` and contains
`request`, `initiation`, `novaAdmission`, `evidence` (the signed specialty
envelopes), `finalReceipts`, `initialSnapshot`, and `finalSnapshot`. Each
contract follows the corresponding v0.1 type above; unknown fields are rejected.
The evaluator uses the process clock, accepts at most 1 MiB from stdin, and
returns a structured HOLD/STOP/PENDING result as JSON. Exit code 2 means the
input could not be processed; an evaluation that returns a restrictive status
is still a successful evaluation and exits 0.

This command is useful for local contract evaluation only. The two snapshot
fields must be independently obtained by the host, but their authenticity is
not established by the CLI. It makes no network calls and does not deliver
messages, open contact, or enable authority.
