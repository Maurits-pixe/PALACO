import { sign, verify, createHash } from "node:crypto";

const id = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const hash = (v) => createHash("sha256").update(v).digest("hex");
const deny = (reason) => Object.freeze({ verified: false, reason, authorityGranted: false });

const payload = (v) => JSON.stringify({ schema: v.schema, issuer: v.issuer,
  subjectId: v.subjectId, citadelId: v.citadelId, capability: v.capability,
  challenge: v.challenge, sessionDigest: v.sessionDigest,
  issuedAt: v.issuedAt, expiresAt: v.expiresAt, revoked: v.revoked });

// Isolated test fixture issuer. NOT a PALACO ONE production identity issuer.
export function createReviewerProof(fields, privateKey) {
  if (!fields || !id(fields.issuer) || !id(fields.subjectId) || !id(fields.citadelId) ||
      !id(fields.challenge) || !/^[a-f0-9]{64}$/.test(fields.sessionDigest) ||
      fields.capability !== "HARA_RECOVERY_OBSERVE" || fields.revoked !== false ||
      !Number.isSafeInteger(fields.issuedAt) || !Number.isSafeInteger(fields.expiresAt) ||
      fields.issuedAt < 0 || fields.expiresAt <= fields.issuedAt ||
      fields.expiresAt - fields.issuedAt > 60) throw new TypeError("REVIEW_PROOF_INPUT_INVALID");
  const record = { issuer: fields.issuer, subjectId: fields.subjectId,
    citadelId: fields.citadelId, capability: fields.capability,
    challenge: fields.challenge, sessionDigest: fields.sessionDigest,
    issuedAt: fields.issuedAt, expiresAt: fields.expiresAt,
    revoked: fields.revoked, schema: "PALACO_ONE_REVIEWER_PROOF_DRAFT_V1" };
  const signature = sign(null, Buffer.from(payload(record)), privateKey).toString("base64url");
  return Object.freeze({ ...record, signature });
}

export function verifyReviewerProof({ proof, pinnedIssuer, publicKey, challenge,
  citadelId, observedAt, consumedChallenges } = {}) {
  if (!proof || proof.schema !== "PALACO_ONE_REVIEWER_PROOF_DRAFT_V1" ||
      !id(pinnedIssuer) || proof.issuer !== pinnedIssuer ||
      !id(challenge) || proof.challenge !== challenge || !id(citadelId) ||
      proof.citadelId !== citadelId || !id(proof.subjectId) ||
      proof.capability !== "HARA_RECOVERY_OBSERVE" || proof.revoked !== false ||
      !/^[a-f0-9]{64}$/.test(proof.sessionDigest) ||
      !Number.isSafeInteger(observedAt) || !Number.isSafeInteger(proof.issuedAt) ||
      !Number.isSafeInteger(proof.expiresAt) || observedAt < proof.issuedAt ||
      observedAt >= proof.expiresAt || proof.expiresAt - proof.issuedAt > 60 ||
      typeof proof.signature !== "string" || !/^[A-Za-z0-9_-]+$/.test(proof.signature) ||
      !(consumedChallenges instanceof Set) || consumedChallenges.has(challenge)) {
    return deny("REVIEW_PROOF_CONTEXT_DENIED");
  }
  let valid = false;
  try { valid = verify(null, Buffer.from(payload(proof)), publicKey,
    Buffer.from(proof.signature, "base64url")); } catch { valid = false; }
  if (!valid) return deny("REVIEW_PROOF_SIGNATURE_DENIED");
  return Object.freeze({ verified: true, reason: "REVIEW_PROOF_SIGNATURE_ONLY",
    proofDigest: hash(payload(proof)), subjectId: proof.subjectId,
    challengeMustBeConsumedAtomically: true, providerIndependentlyBound: false,
    revocationFreshnessEstablished: false, authorityGranted: false });
}
