import { draftHumanRecoveryReview } from "./human-review-contract.mjs";

const validId = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const hold = (reason) => Object.freeze({ accepted: false, reason, decision: "HOLD",
  authorityGranted: false, contentReleased: false, recoveryExecuted: false });

// Injected PALACO ONE-shaped test port. Provider authenticity is NOT established
// by this module. Even a positive preflight cannot authorize recovery.
export async function draftReviewedRecoveryObservation({ identityClient, sessionReference,
  dossier, citadelId, finding, observedAt, evidenceDigests = [], timeoutMs = 1500 } = {}) {
  if (!identityClient || typeof identityClient.verifyReviewerSession !== "function" ||
      !validId(sessionReference) || !validId(citadelId) ||
      !Number.isSafeInteger(observedAt) || observedAt < 0 ||
      !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 5000) {
    return hold("REVIEW_IDENTITY_PORT_INVALID");
  }
  let timeout;
  let identity;
  try {
    identity = await Promise.race([
      Promise.resolve().then(() => identityClient.verifyReviewerSession(
        Object.freeze({ sessionReference, citadelId, purpose: "HARA_RECOVERY_OBSERVATION", observedAt }))),
      new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error("IDENTITY_TIMEOUT")), timeoutMs);
      })
    ]);
  } catch { return hold("REVIEW_IDENTITY_UNAVAILABLE"); }
  finally { clearTimeout(timeout); }
  if (!identity || identity.schema !== "PALACO_ONE_REVIEWER_PREFLIGHT_V1" ||
      identity.verified !== true || identity.revoked !== false ||
      identity.capability !== "HARA_RECOVERY_OBSERVE" ||
      identity.citadelId !== citadelId || !validId(identity.subjectId) ||
      !Number.isSafeInteger(identity.issuedAt) ||
      !Number.isSafeInteger(identity.expiresAt) || identity.issuedAt > observedAt ||
      observedAt >= identity.expiresAt || identity.expiresAt <= identity.issuedAt) {
    return hold("REVIEW_IDENTITY_DENIED");
  }
  const draft = draftHumanRecoveryReview({ dossier, reviewerId: identity.subjectId,
    citadelId, finding, observedAt, evidenceDigests });
  if (!draft.accepted) return hold(draft.reason);
  // Preserve reviewerAuthenticated=false: this is an untrusted injected port,
  // not a deployment-bound attestation of the real PALACO ONE provider.
  return Object.freeze({ accepted: true, reason: "REVIEW_IDENTITY_PREFLIGHT_ONLY",
    review: draft.review, identityPortClaimedVerified: true,
    identityProviderIndependentlyVerified: false,
    decision: "HOLD", authorityGranted: false,
    contentReleased: false, recoveryExecuted: false });
}
