import { open, readFile, mkdir, rename, unlink } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { randomUUID, createHash } from "node:crypto";

const sha = (value) => createHash("sha256").update(value).digest("hex");
const id = (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);
const validPath = (value) => typeof value === "string" && basename(value) === "reviewer-challenges.json";

export async function loadChallengeRegister(path, citadelId) {
  if (!validPath(path) || !id(citadelId)) throw new TypeError("CHALLENGE_REGISTER_SCOPE_INVALID");
  let raw;
  try { raw = await readFile(path, "utf8"); }
  catch (error) {
    if (error?.code === "ENOENT") return Object.freeze({ revision: 0, consumed: Object.freeze([]) });
    throw error;
  }
  let envelope;
  try { envelope = JSON.parse(raw); } catch { throw new Error("CHALLENGE_REGISTER_CORRUPT"); }
  if (!envelope || envelope.schema !== "HARA_CHALLENGE_REGISTER_V1" ||
      typeof envelope.payload !== "string" || sha(envelope.payload) !== envelope.sha256)
    throw new Error("CHALLENGE_REGISTER_INTEGRITY_FAILED");
  let value;
  try { value = JSON.parse(envelope.payload); }
  catch { throw new Error("CHALLENGE_REGISTER_PAYLOAD_INVALID"); }
  if (!value || value.citadelId !== citadelId ||
      !Number.isSafeInteger(value.revision) || value.revision < 0 ||
      !Array.isArray(value.consumed) || value.consumed.length !== value.revision ||
      value.consumed.length > 100000 ||
      value.consumed.some((v) => typeof v !== "string" || !/^[a-f0-9]{64}$/.test(v)) ||
      new Set(value.consumed).size !== value.consumed.length)
    throw new Error("CHALLENGE_REGISTER_INVALID_STATE");
  return Object.freeze({ revision: value.revision, consumed: Object.freeze(value.consumed) });
}

// Single-host, single-writer append-only intent. No capability is issued.
export async function consumeReviewerChallenge(path, citadelId, issuer, challenge, expectedRevision) {
  if (!validPath(path) || !id(citadelId) || !id(issuer) || !id(challenge) ||
      !Number.isSafeInteger(expectedRevision) || expectedRevision < 0)
    throw new TypeError("CHALLENGE_CONSUME_INPUT_INVALID");
  const challengeDigest = sha(JSON.stringify([citadelId, issuer, challenge]));
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  let lock;
  try { lock = await open(path + ".lock", "wx", 0o600); }
  catch (error) {
    if (error?.code === "EEXIST") throw new Error("CHALLENGE_WRITER_LOCKED");
    throw error;
  }
  let temp;
  try {
    const current = await loadChallengeRegister(path, citadelId);
    if (current.consumed.includes(challengeDigest)) throw new Error("CHALLENGE_REPLAY_DENIED");
    if (current.revision !== expectedRevision) throw new Error("CHALLENGE_STALE_REVISION");
    if (current.revision >= 100000) throw new Error("CHALLENGE_REGISTER_CAPACITY");
    const payload = JSON.stringify({ citadelId, revision: current.revision + 1,
      consumed: [...current.consumed, challengeDigest] });
    const envelope = JSON.stringify({ schema: "HARA_CHALLENGE_REGISTER_V1",
      payload, sha256: sha(payload) });
    temp = join(dirname(path), `.reviewer-challenges-${randomUUID()}.tmp`);
    const file = await open(temp, "wx", 0o600);
    try { await file.writeFile(envelope, "utf8"); await file.sync(); }
    finally { await file.close(); }
    await rename(temp, path);
    temp = undefined;
    const directory = await open(dirname(path), "r");
    try { await directory.sync(); } finally { await directory.close(); }
    return Object.freeze({ committed: true, revision: current.revision + 1,
      challengeDigest, authorityGranted: false, recoveryExecuted: false });
  } finally {
    if (temp) await unlink(temp).catch(() => {});
    await lock.close();
    await unlink(path + ".lock");
  }
}
