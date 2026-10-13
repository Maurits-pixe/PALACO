# 6RI9ADE Rust/Node bridge v0.1

**Status: bridge draft; full protocol interoperability is not established.**
This document compares PALACO's Rust reference evaluator with the Node
reference in [PALACO-Citadel concept PR #35](https://github.com/Maurits-pixe/PALACO-Citadel/pull/35).
It does not assert that one evaluator's PASS is interchangeable with the
other's result.

## Shared primitive exercised by vectors

`crates/palaco-runtime/tests/vectors/6ri9ade-node-reference-v0.1.json` is a
synthetic Node-generated Ed25519 vector. Rust and Node tests independently
check:

- UTF-16 lexical ordering of JSON object keys, compact JSON serialization, and
  safe-integer-only JSON values;
- the exact evidence-signing domain
  `PALACO/6RI9ADE/REFERENCE-EVIDENCE/v0.1` followed by NUL;
- signing bytes, Ed25519 verification, and the canonical envelope SHA-256.

Run the checks with:

```sh
cargo test -p palaco-runtime --test sixri9ade_bridge_vectors
node crates/palaco-runtime/tests/sixri9ade_bridge_vectors.mjs
```

The vector proves only this byte-level primitive for one body. It is not a
full request, snapshot, 18-slot, receipt, or result conformance suite. The key
is test-only and must never be trusted in a deployment.

## Known wire and semantic differences

| Area | Node reference | PALACO Rust binding | Bridge state |
|---|---|---|---|
| Request | `schemaVersion`, request/challenge IDs, full sender/receiver account/device/tenant/world/Citadel/key-version contexts, array scope and policy/binding versions | `schema`, request ID, two participant strings, scalar scope and one context digest | Not interchangeable; no lossless translation contract |
| Specialty evidence | `schemaVersion`, `type`, `id`, `issuerId`, `roleCode`, `contractDigest`, `admissionDigest`, `checkpoint`, `status`, `evidenceDigest`, times | `schema`, issuer/key/evidence IDs, `requestDigest`, `contextDigest`, `specialty`, `result`, times | Missing signed fields in Rust; bridge cannot infer them |
| Human receipts | `stage`, exact contract digest, combined admission digest, and optional complete evidence-set digest | Separate initiation and admission envelope digests plus evidence-set digest | Digest construction and receipt body shape differ |
| Evidence-set digest | Sorts by Node side order and specialty role order, then hashes envelope digests | Sorts envelope digests lexically before hashing their list | Different algorithm; do not reuse final receipts across implementations |
| Trust snapshot | Synthetic classification, checkpoint, exact expected request, challenge/contact state, revocation IDs and PEM issuers with subject/device/key/context bindings | Snapshot status/revision/request digest, revocation lists and raw Ed25519 issuers | Rust snapshot cannot represent all Node host state |
| Result | `safetyVerdict`, `contactEligibility`, checkpoint and explicit `runtimeConnected=false` | `status`, specialty checks, receipt booleans and explicit `runtimeConnected=false` | No common result enum or UI authorization mapping |

The required next protocol change is a jointly reviewed, versioned mapping for
each row, followed by full cross-language vectors covering valid and rejected
requests, all 18 slots, each receipt stage, changed/revoked/expired snapshots,
duplicate IDs, checkpoints, final digests and all output fields. Until that
exists, the Rust and Node evaluators remain separate reference implementations.

## Snapshot trust boundary

`TrustSnapshotProvider` is the Rust host integration interface. Each evaluation
loads two separately signed snapshots bound to the same request digest and
reads host time before and after. Both signatures must verify against the
configured provider/key anchor, the snapshots must be byte-model identical,
and time must not move backwards. Unavailable, invalid, changed, or stale
inputs yield HOLD.

The Rust snapshot envelope is signed over the canonical JSON object containing
`schema`, `providerId`, `keyId`, and the complete `snapshot`, prefixed by
`PALACO/6RI9ADE/TRUST-SNAPSHOT/v0.1` and NUL. The public
`trust_snapshot_signing_bytes` helper defines these bytes for host implementations
and tests. Snapshot signing is a Rust bridge extension, not part of the Node
reference protocol.

This interface does **not** create a trusted provider or trust anchor. A host
must provision the anchor out-of-band, protect key rotation and rollback state,
fetch snapshots from an authenticated authoritative source, enforce freshness,
and supply a trusted clock. No production provider, root key, account directory,
challenge store, or revocation service is provisioned in PALACO. The standalone
CLI still accepts caller-supplied snapshots and is a **synthetic local
evaluator only**; its output is always marked `SYNTHETIC_ONLY`. Do not use that
CLI path as a trusted snapshot source.

Neither this interface nor the test vectors connect accounts, human receipt
issuance, NOVA, E2EE, bodyguard services, an outbox, RIO, or message delivery.
Every result still has `canOpenContact=false`, `operativeAuthority=NONE`,
`runtimeConnected=false`, and `externalSideEffect=false`.

## Release gates

- Full schema and digest mapping agreed with the Node reference maintainers.
- Shared positive and negative vectors pass in both runtimes on the same
  reviewed commit.
- A real host snapshot provider, trust-anchor provisioning, rotation, rollback
  resistance and trustworthy time have separate designs and independent tests.
- Complete security scan and independent code review finish without unresolved
  findings.
- Production accounts, human receipt issuance, E2EE and delivery remain HOLD
  until their own reviewed integrations and release gates exist.
