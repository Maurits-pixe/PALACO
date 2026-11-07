import { verifyChallengeAnchor } from "./challenge-anchor.mjs";

const id = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const hold = (reason, fields = {}) => Object.freeze({
  schema: "HARA_CHALLENGE_RECOVERY_DOSSIER_DRAFT_V1",
  decision: "HOLD_FOR_HUMAN_RECOVERY", reason,
  ...fields, safeToProceed: false, authorityGranted: false,
  recoveryExecuted: false, independentlyVerified: false,
  operationsPermitted: Object.freeze([])
});

// Only composes independently collected observations. Does not touch disk,
// infer external witness custody, or issue a recovery permission.
export function buildChallengeRecoveryDossier({ citadelId, inspection, snapshot,
  anchor, pinnedIssuer, publicKey, observedAt, trustedRevisionFloor,
  evidenceReference } = {}) {
  if (!id(citadelId) || !id(evidenceReference) ||
      !inspection || inspection.status !== "HOLD_FOR_HUMAN_RECOVERY" ||
      inspection.authorityGranted !== false || inspection.recoveryExecuted !== false)
    return hold("DOSSIER_INPUT_UNTRUSTED");
  const base = { citadelId, evidenceReference, inspectionReason: inspection.reason,
    anchorReason: "NOT_EVALUATED", observedRevision: null };
  if (inspection.reason !== "CHALLENGE_RECOVERY_LOCAL_SNAPSHOT_ONLY" ||
      !Number.isSafeInteger(inspection.observedRevision) ||
      inspection.observedRevision < 0 ||
      inspection.observedConsumedCount !== inspection.observedRevision ||
      inspection.externalAnchorVerified !== false)
    return hold("DOSSIER_LOCAL_INSPECTION_BLOCKED", base);
  if (!snapshot || snapshot.revision !== inspection.observedRevision ||
      !Array.isArray(snapshot.consumed) ||
      snapshot.consumed.length !== inspection.observedConsumedCount)
    return hold("DOSSIER_NONATOMIC_SNAPSHOT_MISMATCH", base);
  const result = verifyChallengeAnchor({ anchor, snapshot, citadelId, pinnedIssuer,
    publicKey, observedAt, trustedRevisionFloor });
  const evidence = { ...base, observedRevision: inspection.observedRevision,
    anchorReason: result.reason, snapshotDigest: result.snapshotDigest ?? null };
  if (!result.matched) return hold("DOSSIER_ANCHOR_DISPUTED", evidence);
  return hold("DOSSIER_REVIEW_REQUIRED", {
    ...evidence, anchorCryptographicallyMatched: true,
    humanReviewRequired: true, externalCustodyUnverified: true,
    snapshotAtomicityUnverified: true, writerQuiescenceUnverified: true,
    revocationFreshnessUnverified: true
  });
}
