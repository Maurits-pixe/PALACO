import { createHash } from "node:crypto";

const digest = (value) => createHash("sha256").update(value).digest("hex");
const validId = (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);
const sha = (value) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const findings = new Set(["CONFLICT_OBSERVED", "EVIDENCE_INCOMPLETE", "NO_CONCLUSION"]);
const deny = (reason) => Object.freeze({ accepted: false, reason, decision: "HOLD",
  authorityGranted: false, contentReleased: false, recoveryExecuted: false });

// A review observation is NOT an authenticated or authorized human decision.
// No state mutation, replay allowance, permit, or post-review recovery exists here.
export function draftHumanRecoveryReview({ dossier, reviewerId, citadelId, finding,
  observedAt, evidenceDigests = [] } = {}) {
  if (!dossier || dossier.schema !== "HARA_RECOVERY_DOSSIER_V1" ||
      dossier.decision !== "HOLD_REVIEW_REQUIRED" ||
      dossier.authorityGranted !== false || dossier.contentReleased !== false ||
      dossier.noncePresentAtInspection !== true || dossier.snapshotOnly !== true ||
      dossier.witnessIndependenceVerified !== false || dossier.manifestReverified !== false ||
      !sha(dossier.nonceKeySha256) || !sha(dossier.manifestSignatureSha256) ||
      !Number.isSafeInteger(dossier.nonceStoreRevisionObserved) ||
      dossier.nonceStoreRevisionObserved < 1 ||
      !["WITNESS_AFTER_COMMIT_HOLD", "WITNESS_CHANGED_DURING_COMMIT_HOLD"].includes(dossier.incident) ||
      !validId(dossier.citadelId) || !sha(dossier.dossierSha256)) {
    return deny("REVIEW_DOSSIER_INVALID");
  }
  const { dossierSha256, ...payload } = dossier;
  if (digest(JSON.stringify(payload)) !== dossierSha256) return deny("REVIEW_DOSSIER_INTEGRITY_FAILED");
  if (!validId(citadelId) || citadelId !== dossier.citadelId ||
      !validId(reviewerId) || !findings.has(finding) ||
      !Number.isSafeInteger(observedAt) || observedAt < 0 ||
      !Array.isArray(evidenceDigests) || evidenceDigests.length > 16 ||
      evidenceDigests.some((value) => !sha(value)) ||
      new Set(evidenceDigests).size !== evidenceDigests.length) {
    return deny("REVIEW_INPUT_INVALID");
  }
  const review = {
    schema: "HARA_HUMAN_REVIEW_OBSERVATION_V1", citadelId,
    dossierSha256, reviewerLabel: reviewerId, finding, observedAt,
    evidenceDigests: [...evidenceDigests], reviewerAuthenticated: false,
    reviewerAuthorized: false, evidenceIndependentlyVerified: false,
    nonceReset: false, authorityGranted: false, contentReleased: false,
    decision: "HOLD_PENDING_AUTHORIZED_REVIEW"
  };
  return Object.freeze({ accepted: true, reason: "REVIEW_OBSERVATION_DRAFTED",
    review: Object.freeze({ ...review, evidenceDigests: Object.freeze(review.evidenceDigests),
      observationSha256: digest(JSON.stringify(review)) }), decision: "HOLD",
    authorityGranted: false, contentReleased: false, recoveryExecuted: false });
}
