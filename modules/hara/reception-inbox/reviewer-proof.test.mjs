import assert from "node:assert/strict";
import { generateKeyPairSync, createHash } from "node:crypto";
import { createReviewerProof, verifyReviewerProof } from "./reviewer-proof.mjs";

const key = generateKeyPairSync("ed25519");
const wrong = generateKeyPairSync("ed25519");
const fields = { issuer: "PALACO_ONE_TEST", subjectId: "maurits",
  citadelId: "LA-001", capability: "HARA_RECOVERY_OBSERVE", challenge: "challenge_1",
  sessionDigest: createHash("sha256").update("session").digest("hex"),
  issuedAt: 1000, expiresAt: 1060, revoked: false };
const proof = createReviewerProof(fields, key.privateKey);
const args = { proof, pinnedIssuer: "PALACO_ONE_TEST", publicKey: key.publicKey,
  challenge: "challenge_1", citadelId: "LA-001", observedAt: 1050,
  consumedChallenges: new Set() };
const run = (changes = {}) => verifyReviewerProof({ ...args, ...changes });
const ok = run();
assert.equal(ok.verified, true);
assert.equal(ok.providerIndependentlyBound, false);
assert.equal(ok.authorityGranted, false);
assert.equal(run({ publicKey: wrong.publicKey }).verified, false);
assert.equal(run({ challenge: "challenge_2" }).verified, false);
assert.equal(run({ citadelId: "OTHER" }).verified, false);
assert.equal(run({ pinnedIssuer: "OTHER" }).verified, false);
assert.equal(run({ observedAt: 1060 }).verified, false);
assert.equal(run({ consumedChallenges: new Set(["challenge_1"]) }).verified, false);
assert.equal(run({ consumedChallenges: undefined }).verified, false);
assert.equal(run({ proof: { ...proof, revoked: true } }).verified, false);
assert.equal(run({ proof: { ...proof, subjectId: "changed" } }).verified, false);
assert.throws(() => createReviewerProof({ ...fields, expiresAt: 1100 }, key.privateKey));
console.log("HARA reviewer proof verification tests PASS");
