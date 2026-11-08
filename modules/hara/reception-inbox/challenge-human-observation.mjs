import { createHash } from "node:crypto";

const id = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const sha = (v) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const findings = new Set(["EVIDENCE_INCOMPLETE", "CONFLICT_OBSERVED", "NO_CONCLUSION"]);
const digest = (v) => createHash("sha256").update(v).digest("hex");
const deny = (reason) => Object.freeze({ accepted: false, reason, decision: "HOLD",
  authorityGranted: false, recoveryExecuted: false, operationsPermitted: Object.freeze([]) });

// Pure metadata record: reviewerLabel is an unauthenticated claim, not PALACO ONE identity.
// No mutation, signing, recovery permit, access grant or automated adjudication.
export function draftChallengeHumanObservation({ dossier, citadelId, reviewerLabel,
  finding, observedAt, evidenceDigests = [] } = {}) {
  if (!dossier || dossier.schema !== "HARA_CHALLENGE_RECOVERY_DOSSIER_DRAFT_V1" ||
      dossier.decision !== "HOLD_FOR_HUMAN_RECOVERY" ||
      dossier.safeToProceed !== false || dossier.authorityGranted !== false ||
      dossier.recoveryExecuted !== false || dossier.independentlyVerified !== false ||
      !Array.isArray(dossier.operationsPermitted) || dossier.operationsPermitted.length !== 0 ||
      !id(dossier.citadelId) || !id(dossier.evidenceReference) ||
      !id(citadelId) || dossier.citadelId !== citadelId ||
      !id(reviewerLabel) || !findings.has(finding) ||
      !Number.isSafeInteger(observedAt) || observedAt < 0 ||
      !Array.isArray(evidenceDigests) || evidenceDigests.length > 16 ||
      evidenceDigests.some((v) => !sha(v)) ||
      new Set(evidenceDigests).size !== evidenceDigests.length)
    return deny("CHALLENGE_OBSERVATION_INPUT_DENIED");
  const dossierDigest = digest(JSON.stringify(dossier));
  const record = {
    schema: "HARA_CHALLENGE_HUMAN_OBSERVATION_DRAFT_V1", citadelId,
    dossierDigest, evidenceReference: dossier.evidenceReference, reviewerLabel,
    finding, observedAt, evidenceDigests: [...evidenceDigests],
    reviewerAuthenticated: false, reviewerAuthorized: false,
    evidenceIndependentlyVerified: false, recoveryExecuted: false,
    authorityGranted: false, decision: "HOLD_PENDING_AUTHORIZED_REVIEW"
  };
  return Object.freeze({ accepted: true, reason: "CHALLENGE_OBSERVATION_DRAFTED",
    observation: Object.freeze({ ...record,
      evidenceDigests: Object.freeze(record.evidenceDigests),
      observationDigest: digest(JSON.stringify(record)) }),
    decision: "HOLD", authorityGranted: false, recoveryExecuted: false,
    operationsPermitted: Object.freeze([]) });
}
