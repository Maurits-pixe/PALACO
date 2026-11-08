import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { draftChallengeHumanObservation } from "./challenge-human-observation.mjs";
import { createChallengeObservationProof, verifyChallengeObservationProof } from "./challenge-observation-proof.mjs";

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
const args = { observation, proof, citadelId: "LA", pinnedIssuer: "TEST_ISSUER",
  challenge: "CHALLENGE_1", observedAt: 120, publicKey: keys.publicKey };
const check = (overrides = {}) => verifyChallengeObservationProof({ ...args, ...overrides });
const good = check();
assert.equal(good.verified, true);
assert.equal(good.authorityGranted, false);
assert.equal(good.safeToProceed, false);
assert.equal(good.reviewerAuthenticated, false);
assert.equal(good.challengeIndependentlyConsumed, false);
assert.equal(check({ publicKey: other.publicKey }).reason, "OBSERVATION_PROOF_SIGNATURE_DENIED");
assert.equal(check({ proof: { ...proof, signature: "a" } }).reason, "OBSERVATION_PROOF_SIGNATURE_DENIED");
assert.equal(check({ challenge: "OTHER" }).reason, "OBSERVATION_PROOF_CONTEXT_DENIED");
assert.equal(check({ citadelId: "OTHER" }).reason, "OBSERVATION_PROOF_CONTEXT_DENIED");
assert.equal(check({ pinnedIssuer: "OTHER" }).reason, "OBSERVATION_PROOF_CONTEXT_DENIED");
assert.equal(check({ observedAt: 150 }).reason, "OBSERVATION_PROOF_CONTEXT_DENIED");
assert.equal(check({ observation: { ...observation, finding: "CONFLICT_OBSERVED" } }).reason,
  "OBSERVATION_PROOF_CONTEXT_DENIED");
assert.equal(check({ observation: { ...observation, authorityGranted: true } }).verified, false);
assert.equal(check({ observation: { ...observation, extraAuthority: true } }).verified, false);
assert.throws(() => createChallengeObservationProof({ observation, issuer: "TEST_ISSUER",
  challenge: "CHALLENGE_1", issuedAt: 100, expiresAt: 401 }, keys.privateKey),
  /OBSERVATION_PROOF_INPUT_INVALID/);
console.log("challenge-observation-proof: PASS (test issuer only; HOLD)");
