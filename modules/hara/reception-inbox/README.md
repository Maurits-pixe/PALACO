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

## Single-host nonce reservation storage candidate

`nonce-store.mjs` persists an append-only consumed-nonce list via a single-host exclusive lock and temporary-file sync/rename. It rejects duplicate keys, stale expected revisions, invalid Citadel scope and detected checksum corruption. Run `node modules/hara/reception-inbox/nonce-store.test.mjs` (including a concurrent same-nonce test).

**Severe remaining boundaries:** the module takes a caller-supplied nonce key and does not itself verify authority or signatures. The host must invoke it only after a trusted verification decision and must withhold any protected content until a successful commit. A deleted or maliciously rewritten store can reset/forge the history; SHA-256 is not a trusted external anti-rollback anchor. Crash-stale locks require supervised recovery. Durability under sudden power loss, cross-host concurrency, key trust, migration and production deployment remain unverified. This component does not by itself establish global replay resistance.

## Durable receive preflight composition candidate

`receive-gate.mjs` composes the pinned-key inspection with the single-host nonce store. It first denies mismatched Citadel scope, loads the consumed-nonce snapshot, verifies trust/signature/freshness, and then atomically commits the verified nonce using the observed revision. Only after the commit does it return an opaque preflight receipt (`NONCE_COMMITTED_PRECHECK_ONLY`). Every receipt explicitly has `authorityGranted: false` and `contentReleased: false`; no reception content is returned or sent. Run `node modules/hara/reception-inbox/receive-gate.test.mjs` for replay, revoked key, invalid signature, expired manifest, Citadel mismatch, tampering, invalid storage path, duplicate and concurrent same-nonce checks.

**Not a production receive endpoint:** a caller still supplies the trust snapshot and clock; its authenticity, revocation freshness and external identity binding are not established. Single-host file storage lacks anti-rollback protection, and a lock refusal can conservatively deny a valid concurrent request. The receipt is not authorization to display, transmit, sync or execute protected data. Offline multi-device conflict resolution and the Hannie agenda execution interlock remain separate HOLD gates. No merge, signing, deployment or release is authorized by this candidate.

## Read-only nonce crash and rollback inspection candidate

`nonce-recovery.mjs` inspects the local nonce store for a writer lock, orphan temporary files, unreadable/corrupt state, revision below a caller-supplied minimum, and missing caller-anchored consumed keys. It never clears a lock, repairs state, overwrites evidence, or sends data. Run `node modules/hara/reception-inbox/nonce-recovery.test.mjs` for clean-state and negative tests.

**Evidence boundary:** the supplied lower-bound revision/nonce list is not itself authenticated, independently persisted, or proven fresh. This inspector does not make the storage rollback-resistant and cannot resolve a crash, stale lock, race or multi-host conflict. Even a clean inspection returns `safeToProceed: false`; supervisory verification and protected authorization remain required. Do not treat `inspectionClean` as a release permit. Production and Hannie agenda gates remain HOLD.

## Signed nonce revision anchor candidate

`signed-nonce-anchor.mjs` creates and read-only verifies an Ed25519-signed, Citadel-scoped revision/prefix-hash anchor valid for at most 300 seconds. It compares the current nonce-store prefix against the anchor and invokes the read-only recovery inspection. Run `node modules/hara/reception-inbox/signed-nonce-anchor.test.mjs`. The tests include wrong public key, tampered signature fields, expiry, lower revision, same-revision divergent history, stale lock and corrupt store.

**Anti-rollback remains unproven:** the signing key, pinned verification key, trusted clock and latest anchor must be provisioned and maintained in an independent trust and storage domain. A stale-but-valid signed anchor does not detect rollback to the corresponding old state (explicitly covered by a negative demonstration test). No key management, trusted remote witness, monotonic hardware counter, recovery procedure, cross-host synchronization or authorized production integration exists here. `safeToProceed` and `antiRollbackEstablished` remain `false` even for a matching anchor. The standalone anchor signer is only reference code, not an issuance service. HOLD remains binding.

## External anchor witness contract candidate

`anchor-witness.mjs` models a separately signed witness checkpoint (Citadel, witness ID, monotonic sequence claim, minimum nonce revision, prefix hash and short validity window). It verifies the externally pinned witness key and minimum expected witness sequence, then compares it with the signed nonce anchor and read-only store inspection. Run `node modules/hara/reception-inbox/anchor-witness.test.mjs`. Negative tests cover a stale checkpoint, mismatched anchor, wrong witness key, tampered fields, wrong witness identity, expiry and rolled-back store.

**No independently operating witness exists in this candidate.** The module cannot prove that a sequence is monotonic, that the caller's minimum sequence is fresh, or that the witness runs in another trust/storage domain. Its fixture signer is not a PALACO signing service. Tests deliberately demonstrate that rolling back the externally supplied minimum witness sequence also defeats stale-checkpoint detection. Protected reception content, issuance, authorization, deployment and synchronization remain blocked. Every positive inspection explicitly returns `safeToProceed: false` and `antiRollbackEstablished: false`; production HOLD is unchanged.

## Single-host witness register hardening candidate

`witness-register.mjs` provides a separately named, single-host, atomically replaced witness checkpoint file. Before storing a checkpoint it verifies the supplied Ed25519 witness signature, Citadel/witness identity, short validity window, expected current sequence, exactly next sequence, nondecreasing minimum revision and consistent hash at unchanged revision. It uses an exclusive writer lock and sync/rename/sync writes. Run `node modules/hara/reception-inbox/witness-register.test.mjs` for duplicate/replay, sequence gaps, lower revision, conflicting same-revision hash, wrong/tampered signatures, stale expected sequence, corrupt store and simultaneous writers.

**Critical HOLD:** `witness-register.json` is local and replaceable. Its checksum detects accidental corruption, not malicious rollback; deleting or restoring the file can reset the sequence. The signer and host may share a failure domain with the Citadel; trusted clock, independent permission boundary, key lifecycle, external monotonic witness and cross-host consensus are absent. A successful append returns `antiRollbackEstablished: false` and `authorityGranted: false`. This candidate does not integrate with a production receive path, execute reception actions or authorize an HARA/Hannie service.

## Fail-closed external witness adapter contract

`witness-adapter.mjs` accepts an injected read-only `getLatestCheckpoint` client. It has no configured network target, credentials or transport. It bounds the wait (1–5000 ms), denies unavailable/failed/timed-out responses, rejects a remote sequence floor below an independently supplied minimum, rejects checkpoints below that floor, and delegates signature/Citadel/storage consistency to `inspectWitnessedAnchor`. Run `node modules/hara/reception-inbox/witness-adapter.test.mjs`, including negative tests for timeouts, exceptions, missing responses, stale/conflicting floors and tampered checkpoints.

**Integration HOLD:** the external client is a test double; this is not a configured witness service. A remote floor is untrusted until independently authenticated; the caller-supplied sequence floor and clock can be stale or forged, and timeout/abort does not guarantee a remote operation stopped. No payload, identity authorization, encryption, push delivery, deployment or protected action is performed. Every outcome returns `safeToProceed: false` and `contentReleased: false`, even when `evidenceChecked: true`. This only prepares an interface for subsequent human-reviewed integration.

## Double-read witness stability candidate

`witness-stability.mjs` brackets existing witness evidence validation with a second bounded read from the same injected read-only client. It snapshots the first result to detect changes even if a test client mutates and reuses the same response object. It conservatively holds if the witness floor, checkpoint signature/scope, sequence, revision or prefix digest differs, or if the second read fails or times out. Run `node modules/hara/reception-inbox/witness-stability.test.mjs` for stable, changing, mutable, missing, timed-out and first-read-denied cases.

**Not linearizability or authority:** two matching observations do not prove an independently operated witness, freshness after the second read, atomicity with a nonce commit, non-equivocation, or trustworthy clock/transport. The client is injected and no real network endpoint is configured. `safeToProceed: false`, `authorityGranted: false` and `contentReleased: false` are invariant. No production, merge, signing, push or Hannie agenda activation is authorized.

## Witness/nonce commit race candidate

`witnessed-receive.mjs` performs bounded witness double-read inspection before a durable nonce preflight commit and repeats the witness inspection after the commit. If the witness sequence, signed checkpoint signature or advertised floor changes across the commit window, the function returns HOLD with `nonceCommitted: true` and `requiresHumanRecovery: true`, withholding all content. If the post-commit witness is unavailable, it likewise preserves the consumed nonce and holds. Run `node modules/hara/reception-inbox/witnessed-receive.test.mjs` for changed-witness, replay, stable-witness, post-commit outage and pre-commit outage cases.

**Irreversibility and authority boundary:** a successful nonce commit is not undone when later witness checks fail; this is deliberate replay safety, but it can require supervised recovery. Re-checking does not create an atomic distributed transaction, trusted witness infrastructure, global replay protection, or production authorization. A witness could change immediately after the final read. Every outcome has `contentReleased: false` and `authorityGranted: false`; even `accepted: true` means only an isolated preflight receipt. A live HARA reception / Hannie agenda adapter is still NOT wired. DRAFT, INTEGRATION HOLD and PRODUCTION HOLD remain unchanged.

## Post-commit witness conflict dossier (read-only)

`recovery-dossier.mjs` constructs a privacy-minimized, deterministic SHA-256 evidence snapshot only for the two explicit witnessed-receive post-commit HOLD outcomes. It checks that the consumed nonce appears in the same-Citadel local nonce store; records revision, incident reason, opaque nonce/signature hashes and a dossier digest; and returns `HOLD_REVIEW_REQUIRED`. Run `node modules/hara/reception-inbox/recovery-dossier.test.mjs`. Negative cases cover missing nonce, wrong scope, ineligible outcome, unreadable/corrupt store, and absence of raw nonce/signature in the result.

This snapshot is **not cryptographic proof of honest storage or independent witnessing**. It does not reverify a signed manifest, establish writer quiescence or read atomicity, authenticate a human reviewer, decide recovery, reset a consumed nonce, release content or grant authority. Original evidence must be preserved for a separately authorized human review. **INTEGRATION HOLD / PRODUCTION HOLD** remain unchanged.

## Human recovery observation contract (non-authorizing)

`human-review-contract.mjs` validates a read-only dossier digest and Citadel scope, then drafts a deterministic observation for `CONFLICT_OBSERVED`, `EVIDENCE_INCOMPLETE`, or `NO_CONCLUSION`, with explicit supplied observation time and opaque evidence digests. Run `node modules/hara/reception-inbox/human-review-contract.test.mjs`. Tests reject tampered dossiers, mismatched scope, invalid reviewer labels, approval-like findings, bad time and duplicate/raw evidence.

A reviewer label is **not proof of an authenticated or authorized human**. The observation never grants authority, resets a consumed nonce, releases content, executes recovery, approves a PR or changes persistent state. Separate authenticated human governance and independent verification remain mandatory. **INTEGRATION HOLD / PRODUCTION HOLD** remain unchanged.

## Reviewer identity preflight adapter (injected test port)

`reviewer-identity-adapter.mjs` calls an injected `verifyReviewerSession` port using an opaque session reference, Citadel scope, explicit observation time and purpose. It bounds waits to 1–5000 ms and fail-closes on timeout, error, invalid response schema, revoked/expired session, wrong Citadel or missing `HARA_RECOVERY_OBSERVE` claim. It can only draft the prior non-authorizing observation contract. Run `node modules/hara/reception-inbox/reviewer-identity-adapter.test.mjs`.

**No real PALACO ONE provider has been connected or authenticated.** A test-port claim of `verified: true` is not independent identity evidence, and the draft deliberately retains `reviewerAuthenticated: false`, `reviewerAuthorized: false`, `authorityGranted: false`, `contentReleased: false`, `recoveryExecuted: false`. The port call has no cancellation contract: after a local timeout the untrusted provider may still finish; it must be side-effect-free. Provider binding, identity key validation, current revocation consistency, replay safeguards and independently reviewed policy remain required. DRAFT / INTEGRATION HOLD / PRODUCTION HOLD remain unchanged.

## Signed reviewer proof fixture (isolated, non-authorizing)

`reviewer-proof.mjs` signs a deliberately DRAFT Ed25519 fixture and verifies a bounded (maximum 60-second) issuer-pinned, Citadel-scoped, challenge-bound proof against an injected public key. Negative tests reject wrong keys, challenge, scope, issuer, expiration, altered fields, revoked claim and previously-consumed challenge snapshots. Run `node modules/hara/reception-inbox/reviewer-proof.test.mjs`.

**Important:** `consumedChallenges` is an externally supplied read-only Set: this verifier does not commit challenge consumption, prove atomic replay prevention or verify independently fresh revocation. The fixture issuer `PALACO_ONE_TEST` is not a production authority; no real PALACO ONE key, session or live provider is bound. `verified: true` means signature/context precheck only, never recovery approval. Integration, release and production HOLD remain in force.

## Single-host reviewer challenge register candidate

`challenge-register.mjs` implements an isolated single-host challenge-consumption store, with exclusive writer lock, expected revision, SHA-256 envelope, write/fsync/rename and directory sync. It stores only digests of scoped challenge tuples and denies already-recorded use. `challenge-register.test.mjs` covers duplicate consumption, stale revision, parallel racing writers, lock collision, scope mismatch and corrupted storage. Run `node modules/hara/reception-inbox/challenge-register.test.mjs`.

This register is **not yet composed atomically** with `reviewer-proof.mjs` verification or live PALACO ONE revocation checks. A deleted/rolled-back file or forged coherent hash envelope is not detectable without an independent trusted anchor; stale crash locks require supervised recovery. No distributed consistency, encryption or real identity authority is established. A committed challenge never grants recovery or content access. DRAFT / INTEGRATION HOLD / PRODUCTION HOLD remain unchanged.

## Signature verification plus challenge consumption (isolated composition)

`reviewer-proof-consume.mjs` combines offline reviewer proof verification with one-time challenge registration. A failed signature never writes. After a verified scoped proof, the storage adapter races through a single-host exclusive lock and revision check; at most one concurrent request can commit the same challenge. Unreadable/corrupt storage and ambiguous commits fail closed. `reviewer-proof-consume.test.mjs` includes parallel race, signature denial, replay, wrong scope, expiry and corruption cases.

This is a **preflight only**, not an atomic distributed identity service. The signature proof uses a test issuer and non-live public key. The verification/commit boundary is protected only within the local lock protocol, while externally fresh revocation, crash behavior, rollback detection, real PALACO ONE binding and durable independent anchors remain unproven. A successful consumption does not produce reviewer authority, content release or recovery; all such transitions remain HOLD.
