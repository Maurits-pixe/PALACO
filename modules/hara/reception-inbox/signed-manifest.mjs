import { createHash, sign, verify } from "node:crypto";
import { replayJournal } from "./journal.mjs";

const validId = (value) => typeof value === "string" &&
  /^[A-Za-z0-9_-]{1,64}$/.test(value);
const digest = (data) => createHash("sha256").update(data).digest("hex");

function canonical(fields) {
  return JSON.stringify({ schema: fields.schema, citadelId: fields.citadelId,
    senderDeviceId: fields.senderDeviceId, recipientDeviceId: fields.recipientDeviceId,
    journalRevision: fields.journalRevision, journalSha256: fields.journalSha256,
    issuedAt: fields.issuedAt, expiresAt: fields.expiresAt, nonce: fields.nonce });
}

export function createSignedManifest(journal, context, privateKey) {
  replayJournal(journal);
  if (!context || !validId(context.senderDeviceId) ||
      !validId(context.recipientDeviceId) || !validId(context.nonce) ||
      context.senderDeviceId === context.recipientDeviceId ||
      !Number.isSafeInteger(context.issuedAt) || !Number.isSafeInteger(context.expiresAt) ||
      context.issuedAt < 0 || context.expiresAt <= context.issuedAt ||
      context.expiresAt - context.issuedAt > 300) throw new TypeError("INVALID_MANIFEST_CONTEXT");
  const fields = {
    schema: "HARA_SYNC_MANIFEST_V1", citadelId: journal.citadelId,
    senderDeviceId: context.senderDeviceId, recipientDeviceId: context.recipientDeviceId,
    journalRevision: journal.entries.length, journalSha256: digest(JSON.stringify(journal)),
    issuedAt: context.issuedAt, expiresAt: context.expiresAt, nonce: context.nonce
  };
  const signature = sign(null, Buffer.from(canonical(fields)), privateKey).toString("base64url");
  return Object.freeze({ ...fields, signature });
}

export function verifySignedManifest(manifest, journal, context, publicKey) {
  replayJournal(journal);
  if (!manifest || manifest.schema !== "HARA_SYNC_MANIFEST_V1" || !context ||
      !validId(context.senderDeviceId) || !validId(context.recipientDeviceId) ||
      !Number.isSafeInteger(context.now) || !validId(manifest.nonce) ||
      manifest.citadelId !== journal.citadelId ||
      manifest.senderDeviceId !== context.senderDeviceId ||
      manifest.recipientDeviceId !== context.recipientDeviceId ||
      !Number.isSafeInteger(manifest.issuedAt) || !Number.isSafeInteger(manifest.expiresAt) ||
      context.now < manifest.issuedAt || context.now >= manifest.expiresAt ||
      manifest.expiresAt - manifest.issuedAt > 300 ||
      manifest.journalRevision !== journal.entries.length ||
      manifest.journalSha256 !== digest(JSON.stringify(journal)) ||
      typeof manifest.signature !== "string" || !/^[A-Za-z0-9_-]+$/.test(manifest.signature)) {
    return Object.freeze({ accepted: false, reason: "MANIFEST_CONTEXT_REJECTED" });
  }
  let valid = false;
  try { valid = verify(null, Buffer.from(canonical(manifest)), publicKey,
    Buffer.from(manifest.signature, "base64url")); }
  catch { valid = false; }
  return Object.freeze({ accepted: valid, reason: valid ? "SIGNATURE_VALID_WITHIN_SCOPE" : "SIGNATURE_INVALID",
    authorizationGranted: false, replayProtectionEstablished: false });
}
