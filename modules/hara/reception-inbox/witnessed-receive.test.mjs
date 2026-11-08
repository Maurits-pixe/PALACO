import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { emptyJournal } from "./journal.mjs";
import { createSignedManifest } from "./signed-manifest.mjs";
import { loadNonceStore } from "./nonce-store.mjs";
import { createNonceAnchor } from "./signed-nonce-anchor.mjs";
import { createWitnessCheckpoint } from "./anchor-witness.mjs";
import { witnessedReceivePreflight } from "./witnessed-receive.mjs";

const sender = generateKeyPairSync("ed25519");
const anchorKeys = generateKeyPairSync("ed25519");
const witnessKeys = generateKeyPairSync("ed25519");
const context = { senderDeviceId: "sender", recipientDeviceId: "receiver",
  citadelId: "LA-001", now: 1050 };
const journal = emptyJournal("LA-001");
const pinned = [{ deviceId: "sender", citadelId: "LA-001", revoked: false,
  publicKeyDer: sender.publicKey.export({ format: "der", type: "spki" }).toString("base64") }];
const dir = await mkdtemp(join(tmpdir(), "hara-witnessed-receive-"));
const file = join(dir, "reception-nonces.json");
try {
  const anchor = createNonceAnchor("LA-001", await loadNonceStore(file, "LA-001"),
    { anchorId: "anchor", issuedAt: 1000, expiresAt: 1100 }, anchorKeys.privateKey);
  const checkpoint = (seq) => createWitnessCheckpoint(anchor, {
    witnessId: "witness", sequence: seq, issuedAt: 1000, expiresAt: 1100
  }, witnessKeys.privateKey);
  const a = { checkpoint: checkpoint(2), sequenceFloor: 2 };
  const b = { checkpoint: checkpoint(3), sequenceFloor: 3 };
  const run = (client, nonce = "nonce_1", changes = {}) => witnessedReceivePreflight({
    client, nonceStorePath: file, manifest: createSignedManifest(journal, {
      senderDeviceId: "sender", recipientDeviceId: "receiver", nonce,
      issuedAt: 1000, expiresAt: 1100 }, sender.privateKey),
    journal, context, trustSnapshot: pinned, anchor,
    anchorPublicKey: anchorKeys.publicKey,
    witnessPublicKey: witnessKeys.publicKey,
    pinnedWitnessId: "witness", trustedSequenceFloor: 2,
    now: 1050, timeoutMs: 25, ...changes
  });
  let calls = 0;
  const raced = await run({ getLatestCheckpoint: async () => {
    calls += 1;
    return calls <= 2 ? a : b;
  } });
  assert.equal(raced.reason, "WITNESS_CHANGED_DURING_COMMIT_HOLD");
  assert.equal(raced.nonceCommitted, true);
  assert.equal(raced.requiresHumanRecovery, true);
  assert.equal(raced.contentReleased, false);
  assert.equal((await loadNonceStore(file, "LA-001")).revision, 1);
  assert.equal((await run({ getLatestCheckpoint: async () => a })).reason,
    "NONCE_COMMIT_PRECHECK_DENIED");
  assert.equal((await loadNonceStore(file, "LA-001")).revision, 1);

  const valid = await run({ getLatestCheckpoint: async () => a }, "nonce_2");
  assert.equal(valid.accepted, true);
  assert.equal(valid.authorityGranted, false);
  assert.equal(valid.contentReleased, false);

  calls = 0;
  const drop = await run({ getLatestCheckpoint: async () => {
    calls += 1;
    return calls <= 2 ? a : null;
  } }, "nonce_3");
  assert.equal(drop.reason, "WITNESS_AFTER_COMMIT_HOLD");
  assert.equal(drop.nonceCommitted, true);
  assert.equal(drop.requiresHumanRecovery, true);
  assert.equal((await loadNonceStore(file, "LA-001")).revision, 3);
  assert.equal((await run({ getLatestCheckpoint: async () => null }, "nonce_4")).reason,
    "WITNESS_BEFORE_COMMIT_HOLD");
  assert.equal((await loadNonceStore(file, "LA-001")).revision, 3);
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA witnessed receive race tests PASS");
