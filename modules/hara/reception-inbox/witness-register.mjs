import { open, readFile, mkdir, rename, unlink } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { createHash, randomUUID, verify } from "node:crypto";

const validId = (s) => typeof s === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(s);
const digest = (s) => typeof s === "string" && /^[0-9a-f]{64}$/.test(s);
const hash = (s) => createHash("sha256").update(s).digest("hex");
const canonical = (v) => JSON.stringify({ schema: v.schema, citadelId: v.citadelId,
  witnessId: v.witnessId, sequence: v.sequence, minimumRevision: v.minimumRevision,
  prefixSha256: v.prefixSha256, issuedAt: v.issuedAt, expiresAt: v.expiresAt });
const goodPath = (p) => typeof p === "string" && basename(p) === "witness-register.json";

export async function loadWitnessRegister(path, citadelId, witnessId) {
  if (!goodPath(path) || !validId(citadelId) || !validId(witnessId)) {
    throw new TypeError("WITNESS_REGISTER_SCOPE_INVALID");
  }
  let raw;
  try { raw = await readFile(path, "utf8"); }
  catch (error) {
    if (error?.code === "ENOENT") return Object.freeze({ sequence: -1, revision: -1, prefixSha256: null });
    throw error;
  }
  let envelope, state;
  try {
    envelope = JSON.parse(raw);
    if (envelope.schema !== "HARA_WITNESS_REGISTER_V1" ||
        hash(envelope.payload) !== envelope.sha256) throw new Error("INTEGRITY");
    state = JSON.parse(envelope.payload);
  } catch { throw new Error("WITNESS_REGISTER_CORRUPT"); }
  if (state.citadelId !== citadelId || state.witnessId !== witnessId ||
      !Number.isSafeInteger(state.sequence) || state.sequence < 0 ||
      !Number.isSafeInteger(state.revision) || state.revision < 0 ||
      !digest(state.prefixSha256)) throw new Error("WITNESS_REGISTER_INVALID_STATE");
  return Object.freeze({ sequence: state.sequence, revision: state.revision,
    prefixSha256: state.prefixSha256 });
}

// Single-host reference store: this is NOT independent witness infrastructure.
// Only signed, scope-bound, sequential checkpoints are accepted.
export async function appendWitnessCheckpoint(path, citadelId, witnessId,
  checkpoint, publicKey, now, expectedSequence) {
  if (!goodPath(path) || !validId(citadelId) || !validId(witnessId) ||
      !checkpoint || checkpoint.schema !== "HARA_NONCE_WITNESS_V1" ||
      checkpoint.citadelId !== citadelId || checkpoint.witnessId !== witnessId ||
      !Number.isSafeInteger(now) || !Number.isSafeInteger(expectedSequence) ||
      expectedSequence < -1 || !Number.isSafeInteger(checkpoint.sequence) ||
      checkpoint.sequence < 0 || !Number.isSafeInteger(checkpoint.minimumRevision) ||
      checkpoint.minimumRevision < 0 || !digest(checkpoint.prefixSha256) ||
      !Number.isSafeInteger(checkpoint.issuedAt) ||
      !Number.isSafeInteger(checkpoint.expiresAt) ||
      now < checkpoint.issuedAt || now >= checkpoint.expiresAt ||
      checkpoint.expiresAt - checkpoint.issuedAt > 300 ||
      typeof checkpoint.signature !== "string" ||
      !/^[A-Za-z0-9_-]+$/.test(checkpoint.signature)) {
    throw new TypeError("WITNESS_REGISTER_INPUT_INVALID");
  }
  let valid = false;
  try { valid = verify(null, Buffer.from(canonical(checkpoint)), publicKey,
    Buffer.from(checkpoint.signature, "base64url")); }
  catch { valid = false; }
  if (!valid) throw new Error("WITNESS_SIGNATURE_DENIED");

  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  let lock;
  try { lock = await open(path + ".lock", "wx", 0o600); }
  catch (error) {
    if (error?.code === "EEXIST") throw new Error("WITNESS_WRITER_LOCKED");
    throw error;
  }
  let temp;
  try {
    const current = await loadWitnessRegister(path, citadelId, witnessId);
    if (current.sequence !== expectedSequence) throw new Error("WITNESS_STALE_SEQUENCE");
    if (checkpoint.sequence !== current.sequence + 1) throw new Error("WITNESS_SEQUENCE_GAP_OR_REPLAY");
    if (checkpoint.minimumRevision < current.revision) throw new Error("WITNESS_REVISION_ROLLBACK");
    if (checkpoint.minimumRevision === current.revision &&
        checkpoint.prefixSha256 !== current.prefixSha256) throw new Error("WITNESS_SAME_REVISION_CONFLICT");
    const payload = JSON.stringify({ citadelId, witnessId, sequence: checkpoint.sequence,
      revision: checkpoint.minimumRevision, prefixSha256: checkpoint.prefixSha256 });
    const data = JSON.stringify({ schema: "HARA_WITNESS_REGISTER_V1", payload,
      sha256: hash(payload) });
    temp = join(dirname(path), ".witness-register-" + randomUUID() + ".tmp");
    const handle = await open(temp, "wx", 0o600);
    try { await handle.writeFile(data, "utf8"); await handle.sync(); }
    finally { await handle.close(); }
    await rename(temp, path);
    temp = undefined;
    const dir = await open(dirname(path), "r");
    try { await dir.sync(); }
    finally { await dir.close(); }
    return Object.freeze({ stored: true, sequence: checkpoint.sequence,
      authorityGranted: false, antiRollbackEstablished: false });
  } finally {
    if (temp) await unlink(temp).catch(() => {});
    await lock.close();
    await unlink(path + ".lock");
  }
}
