import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { emptyJournal } from "./journal.mjs";
import { createSignedManifest } from "./signed-manifest.mjs";
import { inspectAndReserve } from "./trust-gate.mjs";

const keys = generateKeyPairSync("ed25519");
const wrong = generateKeyPairSync("ed25519");
const journal = emptyJournal("LA-001");
const m = createSignedManifest(journal, { senderDeviceId: "device_a",
  recipientDeviceId: "device_b", nonce: "nonce_001", issuedAt: 1000, expiresAt: 1100 }, keys.privateKey);
const ctx = { senderDeviceId: "device_a", recipientDeviceId: "device_b", citadelId: "LA-001", now: 1050 };
const pinned = (key, revoked = false) => [{ deviceId: "device_a", citadelId: "LA-001",
  revoked, publicKeyDer: key.export({ format: "der", type: "spki" }).toString("base64") }];
const trust = pinned(keys.publicKey);
const accepted = inspectAndReserve(m, journal, ctx, trust, []);
assert.equal(accepted.accepted, true);
assert.equal(accepted.authorityGranted, false);
assert.equal(accepted.durableReplayProtectionEstablished, false);
assert.equal(inspectAndReserve(m, journal, ctx, trust, accepted.nextNonces).reason, "NONCE_REPLAY_DENIED");
assert.equal(inspectAndReserve(m, journal, ctx, [], []).reason, "DEVICE_TRUST_DENIED");
assert.equal(inspectAndReserve(m, journal, ctx, pinned(keys.publicKey, true), []).reason, "DEVICE_TRUST_DENIED");
assert.equal(inspectAndReserve(m, journal, ctx, pinned(wrong.publicKey), []).accepted, false);
assert.equal(inspectAndReserve(m, journal, { ...ctx, citadelId: "OTHER" }, trust, []).reason, "SCOPE_DENIED");
assert.equal(inspectAndReserve(m, journal, { ...ctx, now: 1100 }, trust, []).accepted, false);
assert.equal(inspectAndReserve(m, journal, ctx, [...trust, ...trust], []).reason, "DEVICE_TRUST_DENIED");
console.log("HARA trust-gate tests PASS");
