import assert from "node:assert/strict";
import { draftChallengeIncidentReport } from "./challenge-incident-report.mjs";

const inspection = { status: "HOLD_FOR_HUMAN_RECOVERY",
  reason: "POSTCOMMIT_ROLLBACK_SUSPECTED", authorityGranted: false,
  recoveryExecuted: false, challengeReissued: false,
  safeToProceed: false, independentCustodyEstablished: false,
  unexpectedPrivateValue: "DO_NOT_COPY" };
const args = { citadelId: "LA", incidentId: "INC001", inspectedAt: 100,
  inspection, evidenceDigests: ["a".repeat(64)] };
const run = (patch = {}) => draftChallengeIncidentReport({ ...args, ...patch });
const first = run();
assert.equal(first.accepted, true);
assert.equal(first.report.reportDigest, run().report.reportDigest);
assert.equal(first.report.inspectionReason, "POSTCOMMIT_ROLLBACK_SUSPECTED");
assert.equal(first.report.humanReviewRequired, true);
assert.equal(first.report.evidenceCustodyVerified, false);
assert.equal(first.report.incidentResolved, false);
assert.equal(first.report.authorityGranted, false);
assert.equal(first.recoveryExecuted, false);
assert.equal(JSON.stringify(first).includes("DO_NOT_COPY"), false);
assert.equal(Object.isFrozen(first.report.evidenceDigests), true);
assert.equal(run({ inspection: { ...inspection, status: "GO" } }).accepted, false);
assert.equal(run({ inspection: { ...inspection, authorityGranted: true } }).accepted, false);
assert.equal(run({ inspection: { ...inspection, reason: "CUSTOM_APPROVAL" } }).accepted, false);
assert.equal(run({ evidenceDigests: ["a".repeat(64), "a".repeat(64)] }).accepted, false);
assert.equal(run({ incidentId: "" }).accepted, false);
assert.equal(run({ inspectedAt: -1 }).accepted, false);
console.log("challenge-incident-report: PASS (deterministic metadata; HOLD)");
