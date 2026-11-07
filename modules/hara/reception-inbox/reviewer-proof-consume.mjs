import { verifyReviewerProof } from "./reviewer-proof.mjs";
import { loadChallengeRegister, consumeReviewerChallenge } from "./challenge-register.mjs";

const hold = (reason, challengeCommitted = false) => Object.freeze({
  accepted: false, reason, challengeCommitted, decision: "HOLD",
  authorityGranted: false, contentReleased: false, recoveryExecuted: false
});

// Isolated composition: signature check -> persisted one-time claim.
// This is NOT live PALACO ONE authentication or authorization.
export async function verifyAndConsumeReviewerProof({ proof, pinnedIssuer, publicKey,
  challenge, citadelId, observedAt, registerPath } = {}) {
  let store;
  try { store = await loadChallengeRegister(registerPath, citadelId); }
  catch { return hold("REVIEW_CHALLENGE_REGISTER_UNAVAILABLE"); }
  const checked = verifyReviewerProof({ proof, pinnedIssuer, publicKey,
    challenge, citadelId, observedAt, consumedChallenges: new Set() });
  if (!checked.verified) return hold(checked.reason);
  let committed;
  try {
    committed = await consumeReviewerChallenge(registerPath, citadelId,
      pinnedIssuer, challenge, store.revision);
  } catch (error) {
    // A racing commit, failed directory fsync or lock ambiguity must never
    // release a review observation or permit. Manual inspection may be needed.
    return hold(error?.message === "CHALLENGE_REPLAY_DENIED" ?
      "REVIEW_CHALLENGE_REPLAY_DENIED" : "REVIEW_CHALLENGE_COMMIT_HOLD");
  }
  return Object.freeze({ accepted: true, reason: "REVIEW_PROOF_CONSUMED_PRECHECK_ONLY",
    challengeCommitted: committed.committed, challengeRevision: committed.revision,
    proofDigest: checked.proofDigest, subjectId: checked.subjectId,
    providerIndependentlyBound: false, revocationFreshnessEstablished: false,
    decision: "HOLD", authorityGranted: false, contentReleased: false,
    recoveryExecuted: false });
}
