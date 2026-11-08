import { createHash } from "node:crypto";
import { loadNonceStore } from "./nonce-store.mjs";

const digest = (value) => createHash("sha256").update(value).digest("hex");
const validId = (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);
const recoveryReasons = new Set([
  "WITNESS_AFTER_COMMIT_HOLD", "WITNESS_CHANGED_DURING_COMMIT_HOLD"
]);
const held = (reason) => Object.freeze({ readyForHumanReview: false, reason,
  authorityGranted: false, contentReleased: false, decision: "HOLD" });

// Evidence snapshot only. Neither manifest authentication nor a witness's
// independence is established here; the caller must retain original evidence.
export async function prepareRecoveryDossier({ outcome, manifest, context,
  nonceStorePath } = {}) {
  if (!outcome || outcome.accepted !== false || outcome.nonceCommitted !== true ||
      outcome.requiresHumanRecovery !== true || !recoveryReasons.has(outcome.reason)) {
    return held("RECOVERY_OUTCOME_NOT_ELIGIBLE");
  }
  if (!manifest || manifest.schema !== "HARA_SYNC_MANIFEST_V1" ||
      !context || !validId(context.citadelId) || !validId(context.senderDeviceId) ||
      !validId(context.recipientDeviceId) || !validId(manifest.nonce) ||
      manifest.citadelId !== context.citadelId ||
      manifest.senderDeviceId !== context.senderDeviceId ||
      manifest.recipientDeviceId !== context.recipientDeviceId ||
      typeof manifest.signature !== "string" ||
      !/^[A-Za-z0-9_-]+$/.test(manifest.signature)) {
    return held("RECOVERY_SCOPE_INVALID");
  }
  const nonceKey = `${context.citadelId}:${context.senderDeviceId}:${manifest.nonce}`;
  let store;
  try { store = await loadNonceStore(nonceStorePath, context.citadelId); }
  catch { return held("RECOVERY_NONCE_STORE_UNREADABLE"); }
  if (!store.consumed.includes(nonceKey)) return held("RECOVERY_NONCE_EVIDENCE_MISSING");
  const record = {
    schema: "HARA_RECOVERY_DOSSIER_V1",
    incident: outcome.reason,
    citadelId: context.citadelId,
    nonceKeySha256: digest(nonceKey),
    manifestSignatureSha256: digest(manifest.signature),
    nonceStoreRevisionObserved: store.revision,
    noncePresentAtInspection: true,
    snapshotOnly: true,
    witnessIndependenceVerified: false,
    manifestReverified: false,
    authorityGranted: false,
    contentReleased: false,
    decision: "HOLD_REVIEW_REQUIRED"
  };
  return Object.freeze({ readyForHumanReview: true, reason: "RECOVERY_DOSSIER_PREPARED",
    dossier: Object.freeze({ ...record, dossierSha256: digest(JSON.stringify(record)) }),
    authorityGranted: false, contentReleased: false, decision: "HOLD" });
}
