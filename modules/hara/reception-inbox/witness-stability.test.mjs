import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { commitNonce, loadNonceStore } from "./nonce-store.mjs";
import { createNonceAnchor } from "./signed-nonce-anchor.mjs";
import { createWitnessCheckpoint } from "./anchor-witness.mjs";
import { inspectStableWitness } from "./witness-stability.mjs";

const a = generateKeyPairSync("ed25519");
const w = generateKeyPairSync("ed25519");
const dir = await mkdtemp(join(tmpdir(), "hara-stability-"));
const path = join(dir, "reception-nonces.json");
try {
  await commitNonce(path, "LA-001", "LA-001:sender:nonce", 0);
  const anchor = createNonceAnchor("LA-001", await loadNonceStore(path, "LA-001"),
    { anchorId: "anchor", issuedAt: 1000, expiresAt: 1100 }, a.privateKey);
  const checkpoint = createWitnessCheckpoint(anchor, {
    witnessId: "witness", sequence: 4, issuedAt: 1000, expiresAt: 1100
  }, w.privateKey);
  const snapshot = { checkpoint, sequenceFloor: 4 };
  const run = (client) => inspectStableWitness({ client, path, citadelId: "LA-001",
    anchor, anchorPublicKey: a.publicKey, witnessPublicKey: w.publicKey,
    pinnedWitnessId: "witness", trustedSequenceFloor: 4,
    now: 1050, timeoutMs: 25 });
  const same = await run({ getLatestCheckpoint: async () => snapshot });
  assert.equal(same.stable, true);
  assert.equal(same.safeToProceed, false);
  assert.equal(same.contentReleased, false);

  let calls = 0;
  const changed = await run({ getLatestCheckpoint: async () => {
    calls += 1;
    return calls === 1 ? snapshot : { ...snapshot, sequenceFloor: 5 };
  } });
  assert.equal(changed.reason, "STABILITY_SNAPSHOT_CHANGED_HOLD");

  calls = 0;
  const mutable = { checkpoint: { ...checkpoint }, sequenceFloor: 4 };
  assert.equal((await run({ getLatestCheckpoint: async () => {
    calls += 1;
    if (calls === 2) mutable.sequenceFloor = 5;
    return mutable;
  } })).reason, "STABILITY_SNAPSHOT_CHANGED_HOLD");

  calls = 0;
  assert.equal((await run({ getLatestCheckpoint: async () => {
    calls += 1;
    return calls === 1 ? snapshot : null;
  } })).reason, "STABILITY_SECOND_UNAVAILABLE_HOLD");

  calls = 0;
  assert.equal((await run({ getLatestCheckpoint: async () => {
    calls += 1;
    return calls === 1 ? snapshot : new Promise(() => {});
  } })).reason, "STABILITY_SECOND_TIMEOUT_HOLD");

  assert.equal((await run({ getLatestCheckpoint: async () => null })).reason,
    "STABILITY_FIRST_READ_HOLD_WITNESS_UNAVAILABLE_HOLD");
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA witness stability tests PASS");
