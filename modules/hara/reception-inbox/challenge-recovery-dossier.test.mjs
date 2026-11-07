import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { createChallengeAnchor } from "./challenge-anchor.mjs";
import { buildChallengeRecoveryDossier } from "./challenge-recovery-dossier.mjs";

const keys = generateKeyPairSync("ed25519");
const snapshot = { revision: 1, consumed: ["a".repeat(64)] };
const anchor = createChallengeAnchor({ anchorId: "A1", issuer: "TEST",
  citadelId: "LA", snapshot, issuedAt: 100, expiresAt: 150 }, keys.privateKey);
const inspection = { status: "HOLD_FOR_HUMAN_RECOVERY",
  reason: "CHALLENGE_RECOVERY_LOCAL_SNAPSHOT_ONLY", authorityGranted: false,
  recoveryExecuted: false, observedRevision: 1, observedConsumedCount: 1,
  externalAnchorVerified: false };
const args = { citadelId: "LA", evidenceReference: "TEST_EVIDENCE_001",
  inspection, snapshot, anchor, pinnedIssuer: "TEST", publicKey: keys.publicKey,
  observedAt: 120, trustedRevisionFloor: 1 };
const run = (patch = {}) => buildChallengeRecoveryDossier({ ...args, ...patch });
const good = run();
assert.equal(good.reason, "DOSSIER_REVIEW_REQUIRED");
assert.equal(good.anchorCryptographicallyMatched, true);
assert.equal(good.externalCustodyUnverified, true);
assert.equal(good.snapshotAtomicityUnverified, true);
assert.equal(good.decision, "HOLD_FOR_HUMAN_RECOVERY");
assert.equal(good.safeToProceed, false);
assert.equal(good.authorityGranted, false);
assert.equal(good.recoveryExecuted, false);
assert.deepEqual(good.operationsPermitted, []);
assert.equal(JSON.stringify(good).includes("a".repeat(64)), false);
assert.equal(run({ inspection: { ...inspection, reason: "CHALLENGE_RECOVERY_WRITER_LOCK_PRESENT" } }).reason,
  "DOSSIER_LOCAL_INSPECTION_BLOCKED");
assert.equal(run({ inspection: { ...inspection, authorityGranted: true } }).reason,
  "DOSSIER_INPUT_UNTRUSTED");
assert.equal(run({ inspection: { ...inspection, observedRevision: 2, observedConsumedCount: 2 } }).reason,
  "DOSSIER_NONATOMIC_SNAPSHOT_MISMATCH");
assert.equal(run({ snapshot: { revision: 1, consumed: ["b".repeat(64)] } }).anchorReason,
  "ANCHOR_DIGEST_MISMATCH");
assert.equal(run({ trustedRevisionFloor: 2 }).anchorReason,
  "ANCHOR_REVISION_FLOOR_VIOLATED");
assert.equal(run({ observedAt: 150 }).anchorReason, "ANCHOR_CONTEXT_DENIED");
assert.equal(run({ evidenceReference: "" }).reason, "DOSSIER_INPUT_UNTRUSTED");
console.log("challenge-recovery-dossier: PASS (read-only; HOLD)");
