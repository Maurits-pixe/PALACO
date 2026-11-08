import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { emptyJournal, appendJournal } from "./journal.mjs";
import { createSignedManifest, verifySignedManifest } from "./signed-manifest.mjs";

const keys = generateKeyPairSync("ed25519");
const stranger = generateKeyPairSync("ed25519");
const journal = appendJournal(emptyJournal("LA-001"), "RECEPTION", {
  eventId: "arrival_a", citadelId: "LA-001", actorRef: "opaque_a",
  arrivalAt: "2026-11-07T09:00:00Z" });
const context = { senderDeviceId: "device_a", recipientDeviceId: "device_b",
  issuedAt: 1000, expiresAt: 1120, nonce: "nonce_001" };
const m = createSignedManifest(journal, context, keys.privateKey);
const verifyContext = { senderDeviceId: "device_a", recipientDeviceId: "device_b", now: 1050 };
assert.equal(verifySignedManifest(m, journal, verifyContext, keys.publicKey).accepted, true);
assert.equal(verifySignedManifest(m, journal, verifyContext, keys.publicKey).authorizationGranted, false);
assert.equal(verifySignedManifest(m, journal, verifyContext, stranger.publicKey).accepted, false);
assert.equal(verifySignedManifest({ ...m, journalRevision: 9 }, journal, verifyContext, keys.publicKey).accepted, false);
assert.equal(verifySignedManifest(m, journal, { ...verifyContext, recipientDeviceId: "other" }, keys.publicKey).accepted, false);
assert.equal(verifySignedManifest(m, journal, { ...verifyContext, now: 1120 }, keys.publicKey).accepted, false);
const changed = appendJournal(journal, "RECEPTION", { eventId: "arrival_b", citadelId: "LA-001",
  actorRef: "opaque_b", arrivalAt: "2026-11-07T09:01:00Z" });
assert.equal(verifySignedManifest(m, changed, verifyContext, keys.publicKey).accepted, false);
assert.throws(() => createSignedManifest(journal, { ...context, expiresAt: 1400 }, keys.privateKey),
  /INVALID_MANIFEST_CONTEXT/);
console.log("HARA signed manifest tests PASS");
