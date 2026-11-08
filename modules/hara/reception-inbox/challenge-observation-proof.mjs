import { createHash, sign, verify } from "node:crypto";

const id = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const sha = (v) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const findings = new Set(["EVIDENCE_INCOMPLETE", "CONFLICT_OBSERVED", "NO_CONCLUSION"]);
const hash = (v) => createHash("sha256").update(v).digest("hex");
const deny = (reason) => Object.freeze({ verified: false, reason,
  reviewerAuthenticated: false, reviewerAuthorized: false,
  authorityGranted: false, recoveryExecuted: false, safeToProceed: false });

function canonicalObservation(o) {
  if (!o || o.schema !== "HARA_CHALLENGE_HUMAN_OBSERVATION_DRAFT_V1" ||
      !id(o.citadelId) || !id(o.evidenceReference) || !id(o.reviewerLabel) ||
      !sha(o.dossierDigest) || !sha(o.observationDigest) ||
      !findings.has(o.finding) || !Number.isSafeInteger(o.observedAt) ||
      o.observedAt < 0 || !Array.isArray(o.evidenceDigests) ||
      o.evidenceDigests.length > 16 || o.evidenceDigests.some((v) => !sha(v)) ||
      new Set(o.evidenceDigests).size !== o.evidenceDigests.length ||
      o.reviewerAuthenticated !== false || o.reviewerAuthorized !== false ||
      o.evidenceIndependentlyVerified !== false || o.recoveryExecuted !== false ||
      o.authorityGranted !== false || o.decision !== "HOLD_PENDING_AUTHORIZED_REVIEW" ||
      Object.keys(o).length !== 15) return null;
  const record = { schema: o.schema, citadelId: o.citadelId,
    dossierDigest: o.dossierDigest, evidenceReference: o.evidenceReference,
    reviewerLabel: o.reviewerLabel, finding: o.finding,
    observedAt: o.observedAt, evidenceDigests: [...o.evidenceDigests],
    reviewerAuthenticated: false, reviewerAuthorized: false,
    evidenceIndependentlyVerified: false, recoveryExecuted: false,
    authorityGranted: false, decision: "HOLD_PENDING_AUTHORIZED_REVIEW" };
  if (hash(JSON.stringify(record)) !== o.observationDigest) return null;
  return record;
}

const signedMessage = (issuer, challenge, observationDigest, issuedAt, expiresAt) =>
  JSON.stringify({ schema: "HARA_OBSERVATION_PROOF_TEST_V1", issuer,
    challenge, observationDigest, issuedAt, expiresAt });

// Isolated test-issuer signature, not a PALACO ONE-backed signing workflow.
export function createChallengeObservationProof({ observation, issuer, challenge,
  issuedAt, expiresAt } = {}, privateKey) {
  if (!canonicalObservation(observation) || !id(issuer) || !id(challenge) ||
      !Number.isSafeInteger(issuedAt) || issuedAt < 0 ||
      !Number.isSafeInteger(expiresAt) || expiresAt <= issuedAt ||
      expiresAt - issuedAt > 300) throw new TypeError("OBSERVATION_PROOF_INPUT_INVALID");
  const message = signedMessage(issuer, challenge, observation.observationDigest, issuedAt, expiresAt);
  return Object.freeze({ schema: "HARA_OBSERVATION_PROOF_TEST_V1", issuer, challenge,
    observationDigest: observation.observationDigest, issuedAt, expiresAt,
    signature: sign(null, Buffer.from(message), privateKey).toString("base64url") });
}

export function verifyChallengeObservationProof({ observation, proof, citadelId,
  pinnedIssuer, challenge, publicKey, observedAt } = {}) {
  if (!canonicalObservation(observation) || !proof ||
      proof.schema !== "HARA_OBSERVATION_PROOF_TEST_V1" ||
      !id(citadelId) || observation.citadelId !== citadelId ||
      !id(pinnedIssuer) || proof.issuer !== pinnedIssuer ||
      !id(challenge) || proof.challenge !== challenge ||
      proof.observationDigest !== observation.observationDigest ||
      !Number.isSafeInteger(observedAt) || !Number.isSafeInteger(proof.issuedAt) ||
      !Number.isSafeInteger(proof.expiresAt) || proof.issuedAt < 0 ||
      proof.expiresAt <= proof.issuedAt || proof.expiresAt - proof.issuedAt > 300 ||
      observedAt < proof.issuedAt || observedAt >= proof.expiresAt ||
      typeof proof.signature !== "string" || !/^[A-Za-z0-9_-]+$/.test(proof.signature))
    return deny("OBSERVATION_PROOF_CONTEXT_DENIED");
  const message = signedMessage(proof.issuer, proof.challenge, proof.observationDigest,
    proof.issuedAt, proof.expiresAt);
  let valid = false;
  try { valid = verify(null, Buffer.from(message), publicKey,
    Buffer.from(proof.signature, "base64url")); } catch { valid = false; }
  if (!valid) return deny("OBSERVATION_PROOF_SIGNATURE_DENIED");
  return Object.freeze({ verified: true, reason: "TEST_SIGNATURE_MATCH_ONLY",
    reviewerAuthenticated: false, reviewerAuthorized: false, authorityGranted: false,
    recoveryExecuted: false, safeToProceed: false,
    challengeIndependentlyConsumed: false, issuerProductionTrusted: false });
}
