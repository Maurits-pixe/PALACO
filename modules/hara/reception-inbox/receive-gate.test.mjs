import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { emptyJournal } from "./journal.mjs";
import { createSignedManifest } from "./signed-manifest.mjs";
import { receiveManifestPreflight } from "./receive-gate.mjs";
import { loadNonceStore } from "./nonce-store.mjs";

const pair = generateKeyPairSync("ed25519");
const other = generateKeyPairSync("ed25519");
const journal = emptyJournal("LA-001");
const context = { senderDeviceId: "sender_1", recipientDeviceId: "receiver_1",
  citadelId: "LA-001", now: 1050 };
const pinned = (key = pair.publicKey, revoked = false) => [{
  deviceId: "sender_1", citadelId: "LA-001", revoked,
  publicKeyDer: key.export({ format: "der", type: "spki" }).toString("base64")
}];
const manifest = (nonce = "once_1") => createSignedManifest(journal, {
  senderDeviceId: "sender_1", recipientDeviceId: "receiver_1",
  nonce, issuedAt: 1000, expiresAt: 1100
}, pair.privateKey);

const dir = await mkdtemp(join(tmpdir(), "hara-receive-"));
const file = join(dir, "reception-nonces.json");
const invoke = (changes = {}) => receiveManifestPreflight({
  manifest: manifest(), journal, context, trustSnapshot: pinned(),
  nonceStorePath: file, ...changes
});
try {
  const first = await invoke();
  assert.equal(first.reason, "NONCE_COMMITTED_PRECHECK_ONLY");
  assert.equal(first.nonceCommitted, true);
  assert.equal(first.nonceRevision, 1);
  assert.equal(first.authorityGranted, false);
  assert.equal(first.contentReleased, false);
  assert.deepEqual(Object.keys(first).sort(), ["accepted", "authorityGranted",
    "contentReleased", "nonceCommitted", "nonceRevision", "reason"].sort());
  assert.equal((await invoke()).reason, "NONCE_REPLAY_DENIED");
  assert.equal((await invoke({ trustSnapshot: pinned(pair.publicKey, true),
    manifest: manifest("revoked") })).reason, "DEVICE_TRUST_DENIED");
  assert.equal((await invoke({ trustSnapshot: pinned(other.publicKey),
    manifest: manifest("wrong_key") })).reason, "SIGNATURE_INVALID");
  assert.equal((await invoke({ context: { ...context, now: 1100 },
    manifest: manifest("expired") })).reason, "MANIFEST_CONTEXT_REJECTED");
  assert.equal((await invoke({ context: { ...context, citadelId: "OTHER" },
    manifest: manifest("scope") })).reason, "SCOPE_DENIED");
  assert.equal((await invoke({ nonceStorePath: join(dir, "wrong.json"),
    manifest: manifest("path") })).reason, "NONCE_STORE_UNAVAILABLE");
  assert.equal((await invoke({ manifest: { ...manifest("tamper"), nonce: "altered" } })).reason,
    "SIGNATURE_INVALID");
  assert.equal((await invoke({ trustSnapshot: [],
    manifest: manifest("not_trusted") })).reason, "DEVICE_TRUST_DENIED");
  assert.equal((await invoke({ manifest: manifest("valid_2") })).accepted, true);
  const simultaneous = await Promise.all([invoke({ manifest: manifest("race") }),
    invoke({ manifest: manifest("race") })]);
  assert.equal(simultaneous.filter((result) => result.accepted).length, 1);
  assert.equal(simultaneous.filter((result) => !result.accepted).length, 1);
  const state = await loadNonceStore(file, "LA-001");
  assert.equal(state.revision, 3);
  assert.equal(state.consumed.length, 3);
  assert.equal((await invoke({ manifest: manifest("fresh_after_race") })).accepted, true);
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA receive-gate tests PASS");
