import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { draftHumanRecoveryReview } from "./human-review-contract.mjs";

const hash = (v) => createHash("sha256").update(v).digest("hex");
const base = { schema: "HARA_RECOVERY_DOSSIER_V1", incident: "WITNESS_AFTER_COMMIT_HOLD",
  citadelId: "LA-001", nonceKeySha256: hash("opaque"),
  manifestSignatureSha256: hash("signature"), nonceStoreRevisionObserved: 3,
  noncePresentAtInspection: true, snapshotOnly: true,
  witnessIndependenceVerified: false, manifestReverified: false,
  authorityGranted: false, contentReleased: false, decision: "HOLD_REVIEW_REQUIRED" };
const dossier = { ...base, dossierSha256: hash(JSON.stringify(base)) };
const args = { dossier, citadelId: "LA-001", reviewerId: "maurits",
  finding: "CONFLICT_OBSERVED", observedAt: 1000, evidenceDigests: [hash("receipt")] };
const run = (changes = {}) => draftHumanRecoveryReview({ ...args, ...changes });
const first = run();
assert.equal(first.accepted, true);
assert.equal(first.decision, "HOLD");
assert.equal(first.review.reviewerAuthenticated, false);
assert.equal(first.review.reviewerAuthorized, false);
assert.equal(first.review.nonceReset, false);
assert.equal(first.recoveryExecuted, false);
assert.equal(first.review.observationSha256, run().review.observationSha256);
assert.equal(run({ dossier: { ...dossier, incident: "ALTERED" } }).reason,
  "REVIEW_DOSSIER_INVALID");
assert.equal(run({ dossier: { ...dossier, nonceStoreRevisionObserved: 4 } }).reason,
  "REVIEW_DOSSIER_INTEGRITY_FAILED");
assert.equal(run({ citadelId: "OTHER" }).reason, "REVIEW_INPUT_INVALID");
assert.equal(run({ reviewerId: "" }).reason, "REVIEW_INPUT_INVALID");
assert.equal(run({ finding: "APPROVED" }).reason, "REVIEW_INPUT_INVALID");
assert.equal(run({ observedAt: -1 }).reason, "REVIEW_INPUT_INVALID");
assert.equal(run({ evidenceDigests: [hash("receipt"), hash("receipt")] }).reason,
  "REVIEW_INPUT_INVALID");
assert.equal(run({ evidenceDigests: ["raw secret"] }).reason, "REVIEW_INPUT_INVALID");
console.log("HARA human review observation contract tests PASS");
