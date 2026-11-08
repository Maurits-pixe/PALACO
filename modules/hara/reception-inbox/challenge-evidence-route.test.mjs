import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, readFile, rm, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { draftChallengeHumanObservation } from "./challenge-human-observation.mjs";
import { createChallengeObservationProof } from "./challenge-observation-proof.mjs";
import { verifyAndConsumeChallengeObservation } from "./challenge-observation-consume.mjs";
import { loadChallengeRegister } from "./challenge-register.mjs";
import { createChallengeAnchor } from "./challenge-anchor.mjs";
import { inspectPostcommitChallenge } from "./challenge-postcommit-inspection.mjs";
import { draftChallengeIncidentReport } from "./challenge-incident-report.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-evidence-route-"));
const registerPath = join(dir, "reviewer-challenges.json");
const keys = generateKeyPairSync("ed25519");
const otherKeys = generateKeyPairSync("ed25519");
const dossier = {
  schema: "HARA_CHALLENGE_RECOVERY_DOSSIER_DRAFT_V1",
  citadelId: "LA", evidenceReference: "TEST001",
  decision: "HOLD_FOR_HUMAN_RECOVERY", safeToProceed: false,
  authorityGranted: false, recoveryExecuted: false,
  independentlyVerified: false, operationsPermitted: [],
};

try {
  const drafted = draftChallengeHumanObservation({
    dossier, citadelId: "LA", reviewerLabel: "QA_REVIEWER",
    finding: "NO_CONCLUSION", observedAt: 100,
  });
  const observation = drafted.observation;
  const proof = createChallengeObservationProof({
    observation, issuer: "TEST_ISSUER", challenge: "CHALLENGE_1",
    issuedAt: 101, expiresAt: 150,
  }, keys.privateKey);
  const consumeArgs = {
    observation, proof, citadelId: "LA", pinnedIssuer: "TEST_ISSUER",
    publicKey: keys.publicKey, challenge: "CHALLENGE_1",
    observedAt: 120, registerPath,
  };

  const forged = await verifyAndConsumeChallengeObservation({
    ...consumeArgs, publicKey: otherKeys.publicKey,
  });
  assert.equal(forged.accepted, false);
  assert.equal((await loadChallengeRegister(registerPath, "LA")).revision, 0);

  const consumed = await verifyAndConsumeChallengeObservation(consumeArgs);
  assert.equal(consumed.accepted, true);
  assert.equal(consumed.challengeCommitted, true);
  assert.equal(consumed.authorityGranted, false);
  assert.equal(consumed.recoveryExecuted, false);
  const snapshot = await loadChallengeRegister(registerPath, "LA");
  assert.equal(snapshot.revision, 1);
  assert.equal(snapshot.consumed.length, 1);
  const anchor = createChallengeAnchor({
    anchorId: "ANCHOR_1", issuer: "TEST_ISSUER", citadelId: "LA",
    snapshot, issuedAt: 100, expiresAt: 150,
  }, keys.privateKey);
  const inspectArgs = {
    path: registerPath, citadelId: "LA", anchor,
    receipt: { committed: true, revision: 1, challengeDigest: snapshot.consumed[0] },
    pinnedIssuer: "TEST_ISSUER", publicKey: keys.publicKey,
    observedAt: 120, trustedRevisionFloor: 1, evidenceReference: "TEST001",
  };
  const inspect = (overrides = {}) => inspectPostcommitChallenge({ ...inspectArgs, ...overrides });
  const report = (inspection, suffix) => draftChallengeIncidentReport({
    citadelId: "LA", incidentId: `INC${suffix}`, inspectedAt: 120,
    inspection, evidenceDigests: [anchor.snapshotDigest],
  });
  const goodInspection = await inspect();
  assert.equal(goodInspection.reason, "POSTCOMMIT_MATCH_HUMAN_REVIEW_REQUIRED");
  assert.equal(goodInspection.safeToProceed, false);
  const goodReport = report(goodInspection, "001");
  assert.equal(goodReport.accepted, true);
  assert.equal(goodReport.report.incidentResolved, false);
  assert.equal(goodReport.report.authorityGranted, false);
  assert.equal(goodReport.report.reportDigest, report(goodInspection, "001").report.reportDigest);
  const stored = await readFile(registerPath, "utf8");
  assert.equal(stored.includes("QA_REVIEWER"), false);
  assert.equal(stored.includes(observation.observationDigest), false);
  assert.equal(JSON.stringify(goodReport).includes("QA_REVIEWER"), false);

  const replay = await verifyAndConsumeChallengeObservation(consumeArgs);
  assert.equal(replay.reason, "OBSERVATION_CHALLENGE_REPLAY_DENIED");
  assert.equal((await loadChallengeRegister(registerPath, "LA")).revision, 1);

  const missing = await inspect({ receipt: { ...inspectArgs.receipt, challengeDigest: "b".repeat(64) } });
  assert.equal(missing.reason, "POSTCOMMIT_COMMIT_NOT_FOUND");
  assert.equal(report(missing, "002").report.incidentResolved, false);
  const expired = await inspect({ observedAt: 150 });
  assert.equal(expired.reason, "POSTCOMMIT_ANCHOR_OR_DOSSIER_HOLD");
  assert.equal(report(expired, "003").report.authorityGranted, false);

  await writeFile(registerPath + ".lock", "stale", "utf8");
  const locked = await inspect();
  assert.equal(locked.reason, "POSTCOMMIT_LOCAL_HOLD");
  assert.equal(report(locked, "004").report.incidentResolved, false);
  assert.equal((await loadChallengeRegister(registerPath, "LA")).revision, 1);

  // Faults are injected only into this test-owned disposable register.
  await unlink(registerPath + ".lock");
  const wrongKey = await inspect({ publicKey: otherKeys.publicKey });
  assert.equal(wrongKey.reason, "POSTCOMMIT_ANCHOR_OR_DOSSIER_HOLD");
  assert.equal(report(wrongKey, "005").report.authorityGranted, false);
  const rollback = await inspect({ trustedRevisionFloor: 2 });
  assert.equal(rollback.reason, "POSTCOMMIT_ANCHOR_OR_DOSSIER_HOLD");
  assert.equal(report(rollback, "006").report.incidentResolved, false);
  await writeFile(registerPath, "{corrupted-fixture", "utf8");
  const corrupt = await inspect();
  assert.equal(corrupt.reason, "POSTCOMMIT_LOCAL_HOLD");
  assert.equal(report(corrupt, "007").report.authorityGranted, false);
} finally {
  await rm(dir, { recursive: true, force: true });
}
console.log("challenge-evidence-route: PASS (isolated end-to-end; HOLD)");
