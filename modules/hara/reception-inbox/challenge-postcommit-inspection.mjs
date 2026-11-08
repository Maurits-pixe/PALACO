import { inspectChallengeRecovery } from "./challenge-recovery.mjs";
import { loadChallengeRegister } from "./challenge-register.mjs";
import { buildChallengeRecoveryDossier } from "./challenge-recovery-dossier.mjs";

const hex = (v) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const hold = (reason, detail = {}) => Object.freeze({
  status: "HOLD_FOR_HUMAN_RECOVERY", reason, ...detail,
  authorityGranted: false, recoveryExecuted: false, challengeReissued: false,
  safeToProceed: false, independentCustodyEstablished: false
});

// Read-only comparison of a prior commit receipt and independently supplied anchor.
// Inspection and state read are NOT atomic; never repairs or removes a lock.
export async function inspectPostcommitChallenge({ path, citadelId, receipt,
  anchor, pinnedIssuer, publicKey, observedAt, trustedRevisionFloor,
  evidenceReference } = {}) {
  if (!receipt || receipt.committed !== true ||
      !Number.isSafeInteger(receipt.revision) || receipt.revision < 1 ||
      !hex(receipt.challengeDigest)) return hold("POSTCOMMIT_RECEIPT_INVALID");
  const inspection = await inspectChallengeRecovery({ path, citadelId });
  if (inspection.reason !== "CHALLENGE_RECOVERY_LOCAL_SNAPSHOT_ONLY")
    return hold("POSTCOMMIT_LOCAL_HOLD", { inspectionReason: inspection.reason });
  let snapshot;
  try { snapshot = await loadChallengeRegister(path, citadelId); }
  catch { return hold("POSTCOMMIT_READ_AMBIGUOUS"); }
  const secondInspection = await inspectChallengeRecovery({ path, citadelId });
  if (secondInspection.reason !== "CHALLENGE_RECOVERY_LOCAL_SNAPSHOT_ONLY" ||
      secondInspection.observedRevision !== inspection.observedRevision ||
      snapshot.revision !== inspection.observedRevision)
    return hold("POSTCOMMIT_NONATOMIC_STATE_CHANGED");
  if (snapshot.revision < receipt.revision)
    return hold("POSTCOMMIT_ROLLBACK_SUSPECTED", { observedRevision: snapshot.revision });
  if (!snapshot.consumed.includes(receipt.challengeDigest))
    return hold("POSTCOMMIT_COMMIT_NOT_FOUND", { observedRevision: snapshot.revision });
  if (snapshot.consumed[receipt.revision - 1] !== receipt.challengeDigest)
    return hold("POSTCOMMIT_LINEAGE_POSITION_MISMATCH");
  const dossier = buildChallengeRecoveryDossier({ citadelId, inspection, snapshot,
    anchor, pinnedIssuer, publicKey, observedAt, trustedRevisionFloor, evidenceReference });
  if (dossier.reason !== "DOSSIER_REVIEW_REQUIRED")
    return hold("POSTCOMMIT_ANCHOR_OR_DOSSIER_HOLD", {
      dossierReason: dossier.reason, anchorReason: dossier.anchorReason ?? "NOT_EVALUATED" });
  return hold("POSTCOMMIT_MATCH_HUMAN_REVIEW_REQUIRED", {
    observedRevision: snapshot.revision, evidenceReference,
    externalCustodyUnverified: true, writerQuiescenceUnverified: true
  });
}
