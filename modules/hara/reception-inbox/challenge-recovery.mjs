import { lstat, readdir } from "node:fs/promises";
import { basename, dirname } from "node:path";
import { loadChallengeRegister } from "./challenge-register.mjs";

const id = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const hold = (reason, details = {}) => Object.freeze({ status: "HOLD_FOR_HUMAN_RECOVERY",
  reason, safeToProceed: false, authorityGranted: false,
  recoveryExecuted: false, ...details });

// Read-only diagnostic: no lock removal, restore, retry or nonce reset.
export async function inspectChallengeRecovery({ path, citadelId } = {}) {
  if (typeof path !== "string" || basename(path) !== "reviewer-challenges.json" || !id(citadelId))
    return hold("CHALLENGE_RECOVERY_SCOPE_INVALID");
  let files;
  try { files = await readdir(dirname(path)); }
  catch { return hold("CHALLENGE_RECOVERY_DIRECTORY_UNAVAILABLE"); }
  const lockPresent = files.includes("reviewer-challenges.json.lock");
  const temporaryCount = files.filter((name) => /^\.reviewer-challenges-.*\.tmp$/.test(name)).length;
  if (lockPresent) return hold("CHALLENGE_RECOVERY_WRITER_LOCK_PRESENT", { temporaryCount });
  if (temporaryCount) return hold("CHALLENGE_RECOVERY_TEMPORARY_FILES_PRESENT", { temporaryCount });
  let stateFile;
  try { stateFile = await lstat(path); }
  catch (error) {
    if (error?.code === "ENOENT") return hold("CHALLENGE_RECOVERY_STORE_MISSING");
    return hold("CHALLENGE_RECOVERY_STORE_UNREADABLE");
  }
  if (!stateFile.isFile() || stateFile.isSymbolicLink()) return hold("CHALLENGE_RECOVERY_UNSAFE_FILE_TYPE");
  let store;
  try { store = await loadChallengeRegister(path, citadelId); }
  catch { return hold("CHALLENGE_RECOVERY_STORE_INVALID"); }
  // An apparently coherent store remains HOLD: a full file rollback or
  // rewriting both payload and checksum cannot be detected locally.
  return hold("CHALLENGE_RECOVERY_LOCAL_SNAPSHOT_ONLY", {
    observedRevision: store.revision, observedConsumedCount: store.consumed.length,
    temporaryCount: 0, externalAnchorVerified: false
  });
}
