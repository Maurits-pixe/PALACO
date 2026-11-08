import { createHash, sign, verify } from "node:crypto";
import { loadNonceStore } from "./nonce-store.mjs";
import { inspectNonceRecovery } from "./nonce-recovery.mjs";

const validId = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const hash = (values) => createHash("sha256").update(JSON.stringify(values)).digest("hex");
const canonical = (a) => JSON.stringify({ schema: a.schema, citadelId: a.citadelId,
  revision: a.revision, prefixSha256: a.prefixSha256, issuedAt: a.issuedAt,
  expiresAt: a.expiresAt, anchorId: a.anchorId });
const denied = (reason) => Object.freeze({ checked: false, reason,
  authorityGranted: false, safeToProceed: false, antiRollbackEstablished: false });

// Signing material is provided by a separate operator; no key persistence or
// independently trusted clock is established by this reference implementation.
export function createNonceAnchor(citadelId, snapshot, context, privateKey) {
  if (!validId(citadelId) || !snapshot || !context ||
      !validId(context.anchorId) || !Number.isSafeInteger(snapshot.revision) ||
      snapshot.revision < 0 || !Array.isArray(snapshot.consumed) ||
      snapshot.consumed.length !== snapshot.revision ||
      snapshot.consumed.some((v) => typeof v !== "string" || !v.startsWith(citadelId + ":")) ||
      !Number.isSafeInteger(context.issuedAt) || !Number.isSafeInteger(context.expiresAt) ||
      context.issuedAt < 0 || context.expiresAt <= context.issuedAt ||
      context.expiresAt - context.issuedAt > 300) throw new TypeError("ANCHOR_INPUT_INVALID");
  const fields = { schema: "HARA_NONCE_ANCHOR_V1", citadelId,
    revision: snapshot.revision, prefixSha256: hash(snapshot.consumed),
    issuedAt: context.issuedAt, expiresAt: context.expiresAt, anchorId: context.anchorId };
  return Object.freeze({ ...fields, signature: sign(null,
    Buffer.from(canonical(fields)), privateKey).toString("base64url") });
}

// A signed anchor catches mismatch only if its public key and most recent
// anchor are pinned outside the rollback domain. This function is read-only.
export async function inspectSignedNonceAnchor(path, citadelId, anchor, publicKey, now) {
  if (!anchor || anchor.schema !== "HARA_NONCE_ANCHOR_V1" ||
      anchor.citadelId !== citadelId || !validId(anchor.anchorId) ||
      !Number.isSafeInteger(anchor.revision) || anchor.revision < 0 ||
      !Number.isSafeInteger(anchor.issuedAt) || !Number.isSafeInteger(anchor.expiresAt) ||
      !Number.isSafeInteger(now) || now < anchor.issuedAt || now >= anchor.expiresAt ||
      anchor.expiresAt - anchor.issuedAt > 300 ||
      typeof anchor.prefixSha256 !== "string" || !/^[0-9a-f]{64}$/.test(anchor.prefixSha256) ||
      typeof anchor.signature !== "string" || !/^[A-Za-z0-9_-]+$/.test(anchor.signature)) {
    return denied("ANCHOR_CONTEXT_DENIED");
  }
  let signatureValid = false;
  try { signatureValid = verify(null, Buffer.from(canonical(anchor)), publicKey,
    Buffer.from(anchor.signature, "base64url")); }
  catch { return denied("ANCHOR_SIGNATURE_DENIED"); }
  if (!signatureValid) return denied("ANCHOR_SIGNATURE_DENIED");
  let state;
  try { state = await loadNonceStore(path, citadelId); }
  catch { return denied("ANCHOR_STORE_UNAVAILABLE"); }
  if (state.revision < anchor.revision) return denied("ANCHOR_REVISION_ROLLBACK");
  if (hash(state.consumed.slice(0, anchor.revision)) !== anchor.prefixSha256) {
    return denied("ANCHOR_PREFIX_MISMATCH");
  }
  const inspection = await inspectNonceRecovery(path, citadelId, {
    minimumRevision: anchor.revision, requiredNonces: [] });
  if (!inspection.inspectionClean) return denied("ANCHOR_RECOVERY_HOLD");
  return Object.freeze({ checked: true, reason: "SIGNED_ANCHOR_CONSISTENT",
    checkedRevision: state.revision, authorityGranted: false,
    safeToProceed: false, antiRollbackEstablished: false });
}
