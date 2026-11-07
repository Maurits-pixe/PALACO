import { readdir } from "node:fs/promises";
import { basename, dirname } from "node:path";
import { loadNonceStore } from "./nonce-store.mjs";

const validId = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const result = (reason, revision = null, issues = []) => Object.freeze({
  inspectionClean: reason === "CLEAN_WITH_SUPPLIED_ANCHOR", safeToProceed: false, reason,
  revision, issues: Object.freeze(issues), authorityGranted: false,
  rollbackResistanceEstablished: false
});

// Read-only inspector; the caller is responsible for an independently secured,
// current lower-bound revision. This never clears locks or temp files.
export async function inspectNonceRecovery(path, citadelId, anchor) {
  if (typeof path !== "string" || basename(path) !== "reception-nonces.json" ||
      !validId(citadelId) || !anchor || !Number.isSafeInteger(anchor.minimumRevision) ||
      anchor.minimumRevision < 0 ||
      !Array.isArray(anchor.requiredNonces) ||
      anchor.requiredNonces.some((v) => typeof v !== "string" ||
        !v.startsWith(citadelId + ":")) ||
      new Set(anchor.requiredNonces).size !== anchor.requiredNonces.length) {
    return result("RECOVERY_INPUT_INVALID");
  }
  const issues = [];
  try {
    const names = await readdir(dirname(path));
    if (names.includes(basename(path) + ".lock")) issues.push("WRITER_LOCK_PRESENT");
    if (names.some((name) => /^\.reception-nonces-.*\.tmp$/.test(name))) {
      issues.push("ORPHAN_TEMP_PRESENT");
    }
  } catch (error) {
    if (error?.code !== "ENOENT") issues.push("DIRECTORY_INSPECTION_FAILED");
  }
  let state;
  try { state = await loadNonceStore(path, citadelId); }
  catch { return result("STORE_UNREADABLE_HOLD", null, [...issues, "STORE_INVALID"]); }
  if (state.revision < anchor.minimumRevision) issues.push("REVISION_ROLLBACK_SUSPECTED");
  if (anchor.requiredNonces.some((nonce) => !state.consumed.includes(nonce))) {
    issues.push("ANCHORED_NONCE_MISSING");
  }
  // Even a clean inspection is advisory: the snapshot is not locked and may
  // change immediately after the check; the anchor can itself be forged.
  return result(issues.length ? "RECOVERY_HOLD" : "CLEAN_WITH_SUPPLIED_ANCHOR",
    state.revision, issues);
}
