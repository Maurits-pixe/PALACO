import { open, readFile, rename, unlink, mkdir } from "node:fs/promises";
import { dirname, basename, join } from "node:path";
import { randomUUID, createHash } from "node:crypto";

const hash = (data) => createHash("sha256").update(data).digest("hex");
const validId = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const validPath = (v) => typeof v === "string" && basename(v) === "reception-nonces.json";
const validNonceKey = (v, citadelId) => typeof v === "string" &&
  v.startsWith(citadelId + ":") && /^[A-Za-z0-9_:-]{1,194}$/.test(v);

export async function loadNonceStore(path, citadelId) {
  if (!validPath(path) || !validId(citadelId)) throw new TypeError("NONCE_STORE_SCOPE_INVALID");
  let raw;
  try { raw = await readFile(path, "utf8"); }
  catch (error) {
    if (error?.code === "ENOENT") return Object.freeze({ revision: 0, consumed: Object.freeze([]) });
    throw error;
  }
  let envelope;
  try { envelope = JSON.parse(raw); }
  catch { throw new Error("NONCE_STORE_CORRUPT"); }
  if (!envelope || envelope.schema !== "HARA_NONCE_STORE_V1" ||
      typeof envelope.payload !== "string" || hash(envelope.payload) !== envelope.sha256) {
    throw new Error("NONCE_STORE_INTEGRITY_FAILED");
  }
  let value;
  try { value = JSON.parse(envelope.payload); }
  catch { throw new Error("NONCE_STORE_PAYLOAD_INVALID"); }
  if (!value || value.citadelId !== citadelId ||
      !Number.isSafeInteger(value.revision) || value.revision < 0 ||
      !Array.isArray(value.consumed) || value.consumed.length !== value.revision ||
      value.consumed.length > 100000 ||
      value.consumed.some((v) => !validNonceKey(v, citadelId)) ||
      new Set(value.consumed).size !== value.consumed.length) throw new Error("NONCE_STORE_INVALID_STATE");
  return Object.freeze({ revision: value.revision, consumed: Object.freeze(value.consumed) });
}

// Storage-only operation. The caller must verify signature, trust, scope and
// freshness, then invoke this before any protected data access.
export async function commitNonce(path, citadelId, nonceKey, expectedRevision) {
  if (!validPath(path) || !validId(citadelId) || !validNonceKey(nonceKey, citadelId) ||
      !Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
    throw new TypeError("NONCE_COMMIT_INPUT_INVALID");
  }
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const lockPath = path + ".lock";
  let lock;
  try { lock = await open(lockPath, "wx", 0o600); }
  catch (error) {
    if (error?.code === "EEXIST") throw new Error("NONCE_WRITER_LOCKED");
    throw error;
  }
  let tempPath;
  try {
    const current = await loadNonceStore(path, citadelId);
    if (current.consumed.includes(nonceKey)) throw new Error("NONCE_REPLAY_DENIED");
    if (current.revision !== expectedRevision) throw new Error("NONCE_STALE_REVISION");
    if (current.revision >= 100000) throw new Error("NONCE_CAPACITY_REACHED");
    const payload = JSON.stringify({ citadelId, revision: current.revision + 1,
      consumed: [...current.consumed, nonceKey] });
    const data = JSON.stringify({ schema: "HARA_NONCE_STORE_V1", payload, sha256: hash(payload) });
    tempPath = join(dirname(path), ".reception-nonces-" + randomUUID() + ".tmp");
    const file = await open(tempPath, "wx", 0o600);
    try { await file.writeFile(data, "utf8"); await file.sync(); }
    finally { await file.close(); }
    await rename(tempPath, path);
    tempPath = undefined;
    const dir = await open(dirname(path), "r");
    try { await dir.sync(); }
    finally { await dir.close(); }
    return Object.freeze({ revision: current.revision + 1, committed: true });
  } finally {
    if (tempPath) await unlink(tempPath).catch(() => {});
    await lock.close();
    await unlink(lockPath);
  }
}
