import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { generateKeyPairSync } from "node:crypto";
import { consumeReviewerChallenge, loadChallengeRegister } from "./challenge-register.mjs";
import { createChallengeAnchor } from "./challenge-anchor.mjs";
import { inspectPostcommitChallenge } from "./challenge-postcommit-inspection.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-postcommit-"));
const path = join(dir, "reviewer-challenges.json");
const keys = generateKeyPairSync("ed25519");
try {
  const receipt = await consumeReviewerChallenge(path, "LA", "TEST", "CHALLENGE_1", 0);
  const snapshot = await loadChallengeRegister(path, "LA");
  const anchor = createChallengeAnchor({ anchorId: "A1", issuer: "TEST",
    citadelId: "LA", snapshot, issuedAt: 100, expiresAt: 150 }, keys.privateKey);
  const args = { path, citadelId: "LA", receipt, anchor, pinnedIssuer: "TEST",
    publicKey: keys.publicKey, observedAt: 120,
    trustedRevisionFloor: 1, evidenceReference: "TEST001" };
  const run = (o = {}) => inspectPostcommitChallenge({ ...args, ...o });
  const match = await run();
  assert.equal(match.reason, "POSTCOMMIT_MATCH_HUMAN_REVIEW_REQUIRED");
  assert.equal(match.safeToProceed, false);
  assert.equal(match.recoveryExecuted, false);
  assert.equal(match.independentCustodyEstablished, false);
  assert.equal((await run({ receipt: { ...receipt, revision: 2 } })).reason,
    "POSTCOMMIT_ROLLBACK_SUSPECTED");
  assert.equal((await run({ receipt: { ...receipt, challengeDigest: "b".repeat(64) } })).reason,
    "POSTCOMMIT_COMMIT_NOT_FOUND");
  assert.equal((await run({ trustedRevisionFloor: 2 })).reason,
    "POSTCOMMIT_ANCHOR_OR_DOSSIER_HOLD");
  assert.equal((await run({ observedAt: 150 })).reason,
    "POSTCOMMIT_ANCHOR_OR_DOSSIER_HOLD");
  await writeFile(path + ".lock", "stale", "utf8");
  assert.equal((await run()).inspectionReason, "CHALLENGE_RECOVERY_WRITER_LOCK_PRESENT");
  assert.equal((await run()).reason, "POSTCOMMIT_LOCAL_HOLD");
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("challenge-postcommit-inspection: PASS (read-only; HOLD)");
