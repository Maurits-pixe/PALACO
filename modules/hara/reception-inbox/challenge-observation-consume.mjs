import { verifyChallengeObservationProof } from "./challenge-observation-proof.mjs";
import { loadChallengeRegister, consumeReviewerChallenge } from "./challenge-register.mjs";

const hold = (reason, committed = false) => Object.freeze({
  accepted: false, reason, challengeCommitted: committed, decision: "HOLD",
  authorityGranted: false, recoveryExecuted: false, safeToProceed: false,
  issuerIndependentlyVerified: false, reviewerAuthenticated: false
});

// Test fixture composition only. Local one-writer CAS; no distributed atomicity.
export async function verifyAndConsumeChallengeObservation({ observation, proof,
  citadelId, pinnedIssuer, publicKey, challenge, observedAt, registerPath } = {}) {
  let store;
  try { store = await loadChallengeRegister(registerPath, citadelId); }
  catch { return hold("OBSERVATION_REGISTER_UNAVAILABLE"); }
  const result = verifyChallengeObservationProof({ observation, proof, citadelId,
    pinnedIssuer, publicKey, challenge, observedAt });
  if (!result.verified) return hold(result.reason);
  let receipt;
  try {
    receipt = await consumeReviewerChallenge(registerPath, citadelId,
      pinnedIssuer, challenge, store.revision);
  } catch (error) {
    return hold(error?.message === "CHALLENGE_REPLAY_DENIED" ?
      "OBSERVATION_CHALLENGE_REPLAY_DENIED" : "OBSERVATION_CHALLENGE_COMMIT_HOLD");
  }
  return Object.freeze({ accepted: true,
    reason: "TEST_OBSERVATION_CHALLENGE_COMMITTED_HOLD",
    challengeCommitted: receipt.committed, challengeRevision: receipt.revision,
    observationDigest: observation.observationDigest,
    issuerIndependentlyVerified: false, reviewerAuthenticated: false,
    decision: "HOLD", authorityGranted: false, recoveryExecuted: false,
    safeToProceed: false });
}
