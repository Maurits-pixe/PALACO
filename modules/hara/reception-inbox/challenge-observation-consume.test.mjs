import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { draftChallengeHumanObservation } from "./challenge-human-observation.mjs";
import { createChallengeObservationProof } from "./challenge-observation-proof.mjs";
import { verifyAndConsumeChallengeObservation } from "./challenge-observation-consume.mjs";
import { loadChallengeRegister } from "./challenge-register.mjs";

const keys = generateKeyPairSync("ed25519");
const other = generateKeyPairSync("ed25519");
const dossier = { schema: "HARA_CHALLENGE_RECOVERY_DOSSIER_DRAFT_V1",
  citadelId: "LA", evidenceReference: "TEST001", decision: "HOLD_FOR_HUMAN_RECOVERY",
  safeToProceed: false, authorityGranted: false, recoveryExecuted: false,
  independentlyVerified: false, operationsPermitted: [] };
const observation = draftChallengeHumanObservation({ dossier, citadelId: "LA",
  reviewerLabel: "QA_REVIEWER", finding: "NO_CONCLUSION", observedAt: 100 }).observation;
const proof = createChallengeObservationProof({ observation, issuer: "TEST_ISSUER",
  challenge: "CHALLENGE_1", issuedAt: 101, expiresAt: 150 }, keys.privateKey);
const dir = await mkdtemp(join(tmpdir(), "hara-observation-"));
const registerPath = join(dir, "reviewer-challenges.json");
const args = { observation, proof, citadelId: "LA", pinnedIssuer: "TEST_ISSUER",
  publicKey: keys.publicKey, challenge: "CHALLENGE_1", observedAt: 120, registerPath };
const run = (overrides = {}) => verifyAndConsumeChallengeObservation({ ...args, ...overrides });
try {
  const invalid = await run({ publicKey: other.publicKey });
  assert.equal(invalid.accepted, false);
  assert.equal((await loadChallengeRegister(registerPath, "LA")).revision, 0);
  const [first, second] = await Promise.all([run(), run()]);
  assert.equal([first, second].filter((r) => r.accepted).length, 1);
  assert.equal([first, second].filter((r) => r.challengeCommitted).length, 1);
  assert.equal((await loadChallengeRegister(registerPath, "LA")).revision, 1);
  assert.equal(first.authorityGranted, false);
  assert.equal(second.recoveryExecuted, false);
  assert.equal((await run()).reason, "OBSERVATION_CHALLENGE_REPLAY_DENIED");
  assert.equal((await run({ citadelId: "OTHER" })).accepted, false);
  assert.equal((await run({ observedAt: 150 })).accepted, false);
  const stored = await readFile(registerPath, "utf8");
  assert.equal(stored.includes("QA_REVIEWER"), false);
  assert.equal(stored.includes(observation.observationDigest), false);
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("challenge-observation-consume: PASS (single-host test; HOLD)");
