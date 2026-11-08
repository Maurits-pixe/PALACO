import { createPublicKey } from "node:crypto";
import { verifySignedManifest } from "./signed-manifest.mjs";

const id = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);

// A caller provides pinned keys from an independently reviewed authority source.
// This module cannot enroll devices or authorize a PALACO identity.
export function inspectAndReserve(manifest, journal, context, trustSnapshot, nonceSnapshot) {
  if (!context || !id(context.senderDeviceId) || !id(context.recipientDeviceId) ||
      !id(context.citadelId) || !Number.isSafeInteger(context.now) ||
      !Array.isArray(trustSnapshot) || !Array.isArray(nonceSnapshot)) {
    throw new TypeError("TRUST_GATE_INPUT_INVALID");
  }
  const denied = (reason) => Object.freeze({ accepted: false, reason,
    nextNonces: null, authorityGranted: false });
  if (manifest?.citadelId !== context.citadelId || journal?.citadelId !== context.citadelId) {
    return denied("SCOPE_DENIED");
  }
  const matches = trustSnapshot.filter((record) => record &&
    record.citadelId === context.citadelId && record.deviceId === context.senderDeviceId);
  if (matches.length !== 1 || matches[0].revoked !== false ||
      typeof matches[0].publicKeyDer !== "string") return denied("DEVICE_TRUST_DENIED");
  const key = context.citadelId + ":" + context.senderDeviceId + ":" + manifest.nonce;
  if (nonceSnapshot.includes(key)) return denied("NONCE_REPLAY_DENIED");
  let publicKey;
  try {
    publicKey = createPublicKey({ key: Buffer.from(matches[0].publicKeyDer, "base64"),
      format: "der", type: "spki" });
  } catch { return denied("DEVICE_KEY_INVALID"); }
  const verdict = verifySignedManifest(manifest, journal, {
    senderDeviceId: context.senderDeviceId,
    recipientDeviceId: context.recipientDeviceId, now: context.now
  }, publicKey);
  if (!verdict.accepted) return denied(verdict.reason);
  // This reservation must be durably committed by a separate atomic host
  // before any data use. Returning it does not establish replay protection.
  return Object.freeze({ accepted: true, reason: "RESERVATION_PROPOSED",
    nextNonces: Object.freeze([...nonceSnapshot, key]), authorityGranted: false,
    durableReplayProtectionEstablished: false });
}
