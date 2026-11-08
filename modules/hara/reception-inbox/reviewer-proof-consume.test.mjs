import assert from "node:assert/strict";
import { generateKeyPairSync, createHash } from "node:crypto";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createReviewerProof } from "./reviewer-proof.mjs";
import { loadChallengeRegister } from "./challenge-register.mjs";
import { verifyAndConsumeReviewerProof } from "./reviewer-proof-consume.mjs";

const keys = generateKeyPairSync("ed25519");
const other = generateKeyPairSync("ed25519");
const dir = await mkdtemp(join(tmpdir(), "hara-verify-consume-"));
const registerPath = join(dir, "reviewer-challenges.json");
const fields = { issuer: "PALACO_ONE_TEST", subjectId: "maurits", citadelId: "LA-001",
  capability: "HARA_RECOVERY_OBSERVE", challenge: "challenge_1",
  sessionDigest: createHash("sha256").update("session").digest("hex"),
  issuedAt: 1000, expiresAt: 1060, revoked: false };
const proof = createReviewerProof(fields, keys.privateKey);
const args = { proof, pinnedIssuer: "PALACO_ONE_TEST", publicKey: keys.publicKey,
  challenge: "challenge_1", citadelId: "LA-001", observedAt: 1050, registerPath };
const run = (changes = {}) => verifyAndConsumeReviewerProof({ ...args, ...changes });
try {
  assert.equal((await run({ publicKey: other.publicKey })).accepted, false);
  assert.equal((await loadChallengeRegister(registerPath, "LA-001")).revision, 0);
  const raced = await Promise.all([run(), run()]);
  assert.equal(raced.filter((r) => r.accepted).length, 1);
  assert.equal(raced.filter((r) => r.challengeCommitted).length, 1);
  assert.equal(raced.find((r) => r.accepted).authorityGranted, false);
  assert.equal((await loadChallengeRegister(registerPath, "LA-001")).revision, 1);
  assert.equal((await run()).reason, "REVIEW_CHALLENGE_REPLAY_DENIED");
  assert.equal((await run({ citadelId: "OTHER" })).accepted, false);
  assert.equal((await run({ observedAt: 1060 })).accepted, false);
  await writeFile(registerPath, "corrupt");
  assert.equal((await run()).reason, "REVIEW_CHALLENGE_REGISTER_UNAVAILABLE");
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA reviewer proof consume tests PASS");
