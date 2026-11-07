import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { commitNonce, loadNonceStore } from "./nonce-store.mjs";
import { createNonceAnchor } from "./signed-nonce-anchor.mjs";
import { createWitnessCheckpoint } from "./anchor-witness.mjs";
import { inspectExternalWitness } from "./witness-adapter.mjs";

const keyA = generateKeyPairSync("ed25519");
const keyW = generateKeyPairSync("ed25519");
const dir = await mkdtemp(join(tmpdir(), "hara-witness-adapter-"));
const path = join(dir, "reception-nonces.json");
try {
  await commitNonce(path, "LA-001", "LA-001:sender:one", 0);
  const anchor = createNonceAnchor("LA-001", await loadNonceStore(path, "LA-001"),
    { anchorId: "one", issuedAt: 1000, expiresAt: 1100 }, keyA.privateKey);
  const checkpoint = createWitnessCheckpoint(anchor, { witnessId: "witness_1",
    sequence: 2, issuedAt: 1000, expiresAt: 1100 }, keyW.privateKey);
  const snapshot = { checkpoint, sequenceFloor: 2 };
  const run = (client, changes = {}) => inspectExternalWitness({
    client, path, citadelId: "LA-001", anchor, anchorPublicKey: keyA.publicKey,
    witnessPublicKey: keyW.publicKey, pinnedWitnessId: "witness_1",
    trustedSequenceFloor: 2, now: 1050, timeoutMs: 25, ...changes
  });
  const valid = await run({ getLatestCheckpoint: async () => snapshot });
  assert.equal(valid.evidenceChecked, true);
  assert.equal(valid.safeToProceed, false);
  assert.equal(valid.authorityGranted, false);
  assert.equal(valid.contentReleased, false);
  assert.equal((await run({ getLatestCheckpoint: async () => null })).reason,
    "WITNESS_UNAVAILABLE_HOLD");
  assert.equal((await run({ getLatestCheckpoint: async () => { throw new Error("offline"); } })).reason,
    "WITNESS_UNAVAILABLE_HOLD");
  assert.equal((await run({ getLatestCheckpoint: () => new Promise(() => {}) })).reason,
    "WITNESS_TIMEOUT_HOLD");
  assert.equal((await run({ getLatestCheckpoint: async () =>
    ({ checkpoint, sequenceFloor: 1 }) })).reason, "WITNESS_FLOOR_CONFLICT_HOLD");
  assert.equal((await run({ getLatestCheckpoint: async () =>
    ({ checkpoint, sequenceFloor: 3 }) })).reason, "WITNESS_CHECKPOINT_STALE_HOLD");
  assert.equal((await run({ getLatestCheckpoint: async () =>
    ({ checkpoint: { ...checkpoint, prefixSha256: "b".repeat(64) }, sequenceFloor: 2 }) })).reason,
    "WITNESS_PROOF_DENIED_WITNESS_SIGNATURE_DENIED");
  assert.equal((await run({ getLatestCheckpoint: async () => snapshot },
    { trustedSequenceFloor: 3 })).reason, "WITNESS_FLOOR_CONFLICT_HOLD");
  assert.equal((await run(null)).reason, "WITNESS_ADAPTER_INPUT_INVALID");
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA witness adapter tests PASS");
