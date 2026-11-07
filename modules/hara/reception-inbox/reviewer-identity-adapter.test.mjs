import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { draftReviewedRecoveryObservation } from "./reviewer-identity-adapter.mjs";

const hash = (s) => createHash("sha256").update(s).digest("hex");
const raw = { schema: "HARA_RECOVERY_DOSSIER_V1", incident: "WITNESS_AFTER_COMMIT_HOLD",
  citadelId: "LA-001", nonceKeySha256: hash("nonce"),
  manifestSignatureSha256: hash("signature"), nonceStoreRevisionObserved: 1,
  noncePresentAtInspection: true, snapshotOnly: true,
  witnessIndependenceVerified: false, manifestReverified: false,
  authorityGranted: false, contentReleased: false, decision: "HOLD_REVIEW_REQUIRED" };
const dossier = { ...raw, dossierSha256: hash(JSON.stringify(raw)) };
const identity = { schema: "PALACO_ONE_REVIEWER_PREFLIGHT_V1", verified: true,
  revoked: false, capability: "HARA_RECOVERY_OBSERVE", citadelId: "LA-001",
  subjectId: "maurits", issuedAt: 900, expiresAt: 1100 };
const args = { sessionReference: "opaque_ref", dossier, citadelId: "LA-001",
  finding: "NO_CONCLUSION", observedAt: 1000, timeoutMs: 30 };
const run = (answer = identity, changes = {}) => draftReviewedRecoveryObservation({
  ...args, identityClient: { verifyReviewerSession: async () => answer }, ...changes
});
const ok = await run();
assert.equal(ok.accepted, true);
assert.equal(ok.review.reviewerAuthenticated, false);
assert.equal(ok.identityProviderIndependentlyVerified, false);
assert.equal(ok.decision, "HOLD");
assert.equal(ok.recoveryExecuted, false);
for (const bad of [null, { ...identity, verified: false },
  { ...identity, revoked: true }, { ...identity, citadelId: "OTHER" },
  { ...identity, capability: "ADMIN" }, { ...identity, expiresAt: 1000 },
  { ...identity, issuedAt: 1001 }, { ...identity, subjectId: "invalid id" }]) {
  assert.equal((await run(bad)).reason, "REVIEW_IDENTITY_DENIED");
}
assert.equal((await run(identity, { finding: "APPROVED" })).reason,
  "REVIEW_INPUT_INVALID");
assert.equal((await run(identity, { sessionReference: "" })).reason,
  "REVIEW_IDENTITY_PORT_INVALID");
assert.equal((await run(identity, { dossier: { ...dossier, nonceKeySha256: hash("altered") } })).reason,
  "REVIEW_DOSSIER_INTEGRITY_FAILED");
assert.equal((await run(identity, { identityClient: { verifyReviewerSession: () => {
  throw new Error("offline"); } } })).reason, "REVIEW_IDENTITY_UNAVAILABLE");
assert.equal((await run(identity, { identityClient: {
  verifyReviewerSession: () => new Promise(() => {}) }, timeoutMs: 5 })).reason,
  "REVIEW_IDENTITY_UNAVAILABLE");
console.log("HARA reviewer identity adapter tests PASS");
