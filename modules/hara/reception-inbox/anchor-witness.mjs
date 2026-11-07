import { sign, verify } from "node:crypto";
import { inspectSignedNonceAnchor } from "./signed-nonce-anchor.mjs";

const validId = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const digest = (v) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const canonical = (v) => JSON.stringify({ schema: v.schema, citadelId: v.citadelId,
  witnessId: v.witnessId, sequence: v.sequence, minimumRevision: v.minimumRevision,
  prefixSha256: v.prefixSha256, issuedAt: v.issuedAt, expiresAt: v.expiresAt });
const denied = (reason) => Object.freeze({ witnessed: false, reason,
  authorityGranted: false, safeToProceed: false, antiRollbackEstablished: false });

// Offline contract fixture. A production witness must own separate signing keys,
// monotonic persistence, current sequence publication and a trusted time source.
export function createWitnessCheckpoint(anchor, context, privateKey) {
  if (!anchor || anchor.schema !== "HARA_NONCE_ANCHOR_V1" ||
      !validId(anchor.citadelId) || !Number.isSafeInteger(anchor.revision) ||
      anchor.revision < 0 || !digest(anchor.prefixSha256) || !context ||
      !validId(context.witnessId) || !Number.isSafeInteger(context.sequence) ||
      context.sequence < 0 || !Number.isSafeInteger(context.issuedAt) ||
      !Number.isSafeInteger(context.expiresAt) || context.issuedAt < 0 ||
      context.expiresAt <= context.issuedAt || context.expiresAt - context.issuedAt > 300) {
    throw new TypeError("WITNESS_INPUT_INVALID");
  }
  const v = { schema: "HARA_NONCE_WITNESS_V1", citadelId: anchor.citadelId,
    witnessId: context.witnessId, sequence: context.sequence,
    minimumRevision: anchor.revision, prefixSha256: anchor.prefixSha256,
    issuedAt: context.issuedAt, expiresAt: context.expiresAt };
  return Object.freeze({ ...v, signature: sign(null, Buffer.from(canonical(v)),
    privateKey).toString("base64url") });
}

export async function inspectWitnessedAnchor({ path, citadelId, anchor,
  anchorPublicKey, witness, witnessPublicKey, pinnedWitnessId,
  minimumWitnessSequence, now } = {}) {
  if (!witness || witness.schema !== "HARA_NONCE_WITNESS_V1" ||
      !validId(citadelId) || witness.citadelId !== citadelId ||
      !validId(pinnedWitnessId) || witness.witnessId !== pinnedWitnessId ||
      !Number.isSafeInteger(minimumWitnessSequence) || minimumWitnessSequence < 0 ||
      !Number.isSafeInteger(witness.sequence) || witness.sequence < minimumWitnessSequence ||
      !Number.isSafeInteger(witness.minimumRevision) || witness.minimumRevision < 0 ||
      !digest(witness.prefixSha256) ||
      !Number.isSafeInteger(now) || !Number.isSafeInteger(witness.issuedAt) ||
      !Number.isSafeInteger(witness.expiresAt) || now < witness.issuedAt ||
      now >= witness.expiresAt || witness.expiresAt - witness.issuedAt > 300 ||
      typeof witness.signature !== "string" || !/^[A-Za-z0-9_-]+$/.test(witness.signature)) {
    return denied("WITNESS_CONTEXT_DENIED");
  }
  let valid = false;
  try { valid = verify(null, Buffer.from(canonical(witness)), witnessPublicKey,
    Buffer.from(witness.signature, "base64url")); }
  catch { return denied("WITNESS_SIGNATURE_DENIED"); }
  if (!valid) return denied("WITNESS_SIGNATURE_DENIED");
  if (!anchor || anchor.citadelId !== citadelId ||
      anchor.revision !== witness.minimumRevision ||
      anchor.prefixSha256 !== witness.prefixSha256) return denied("WITNESS_ANCHOR_MISMATCH");
  const inspected = await inspectSignedNonceAnchor(path, citadelId, anchor,
    anchorPublicKey, now);
  if (!inspected.checked) return denied("WITNESS_STORE_OR_ANCHOR_HOLD");
  return Object.freeze({ witnessed: true, reason: "WITNESS_CONSISTENT_FOR_SUPPLIED_SNAPSHOT",
    witnessSequence: witness.sequence, authorityGranted: false,
    safeToProceed: false, antiRollbackEstablished: false });
}
