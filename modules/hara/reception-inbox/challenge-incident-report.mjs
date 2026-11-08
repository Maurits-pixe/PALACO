import { createHash } from "node:crypto";

const id = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const sha = (v) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const hash = (v) => createHash("sha256").update(v).digest("hex");
const reasons = new Set([
  "POSTCOMMIT_RECEIPT_INVALID", "POSTCOMMIT_LOCAL_HOLD", "POSTCOMMIT_READ_AMBIGUOUS",
  "POSTCOMMIT_NONATOMIC_STATE_CHANGED", "POSTCOMMIT_ROLLBACK_SUSPECTED",
  "POSTCOMMIT_COMMIT_NOT_FOUND", "POSTCOMMIT_LINEAGE_POSITION_MISMATCH",
  "POSTCOMMIT_ANCHOR_OR_DOSSIER_HOLD", "POSTCOMMIT_MATCH_HUMAN_REVIEW_REQUIRED"
]);
const deny = (reason) => Object.freeze({ accepted: false, reason, decision: "HOLD",
  authorityGranted: false, recoveryExecuted: false });

// Deterministic, metadata-only draft. Evidence source is caller-supplied,
// untrusted until independently preserved and reviewed.
export function draftChallengeIncidentReport({ citadelId, incidentId, inspectedAt,
  inspection, evidenceDigests = [] } = {}) {
  if (!id(citadelId) || !id(incidentId) || !Number.isSafeInteger(inspectedAt) ||
      inspectedAt < 0 || !inspection ||
      inspection.status !== "HOLD_FOR_HUMAN_RECOVERY" || !reasons.has(inspection.reason) ||
      inspection.authorityGranted !== false || inspection.recoveryExecuted !== false ||
      inspection.challengeReissued !== false || inspection.safeToProceed !== false ||
      inspection.independentCustodyEstablished !== false ||
      !Array.isArray(evidenceDigests) || evidenceDigests.length > 16 ||
      evidenceDigests.some((v) => !sha(v)) ||
      new Set(evidenceDigests).size !== evidenceDigests.length)
    return deny("INCIDENT_REPORT_INPUT_DENIED");
  const report = {
    schema: "HARA_CHALLENGE_INCIDENT_REPORT_DRAFT_V1",
    citadelId, incidentId, inspectedAt, inspectionReason: inspection.reason,
    localObservationOnly: true, evidenceDigests: [...evidenceDigests],
    evidenceCustodyVerified: false, issuerIndependentlyVerified: false,
    incidentResolved: false, humanReviewRequired: true,
    authorityGranted: false, recoveryExecuted: false,
    decision: "HOLD_FOR_HUMAN_RECOVERY"
  };
  return Object.freeze({ accepted: true, reason: "INCIDENT_REPORT_DRAFTED",
    report: Object.freeze({ ...report, evidenceDigests: Object.freeze(report.evidenceDigests),
      reportDigest: hash(JSON.stringify(report)) }),
    decision: "HOLD", authorityGranted: false, recoveryExecuted: false });
}
