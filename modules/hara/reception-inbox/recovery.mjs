import { readdir, stat } from "node:fs/promises";
import { dirname, basename } from "node:path";
import { createHash } from "node:crypto";
import { loadLocalJournal } from "./local-store.mjs";
import { inspectBackup } from "./backup.mjs";

async function exists(path) {
  try { await stat(path); return true; }
  catch (error) { if (error?.code === "ENOENT") return false; throw error; }
}

// Observation only. No unlink, rename, restore or lock takeover is possible here.
export async function inspectRecovery({ storePath, backupPath, citadelId }) {
  if (typeof storePath !== "string" || basename(storePath) !== "reception-journal.json" ||
      typeof citadelId !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(citadelId)) {
    throw new TypeError("INVALID_RECOVERY_SCOPE");
  }
  const lockPresent = await exists(storePath + ".lock");
  let tempFiles = [];
  try {
    tempFiles = (await readdir(dirname(storePath)))
      .filter((name) => /^\.reception-journal-[a-f0-9-]+\.tmp$/.test(name));
  } catch (error) { if (error?.code !== "ENOENT") throw error; }
  const storePresent = await exists(storePath);
  let store = { status: "MISSING", entries: null, sha256: null };
  if (storePresent) {
    try {
      const journal = await loadLocalJournal(storePath, citadelId);
      store = { status: "VALID", entries: journal.entries.length,
        sha256: createHash("sha256").update(JSON.stringify(journal)).digest("hex") };
    } catch { store = { status: "INVALID", entries: null, sha256: null }; }
  }
  let backup = { status: "NOT_SUPPLIED", entries: null, sha256: null };
  if (backupPath !== undefined) {
    try {
      const info = await inspectBackup(backupPath, citadelId);
      backup = { status: "VALID", entries: info.entries, sha256: info.sha256 };
    } catch { backup = { status: "INVALID", entries: null, sha256: null }; }
  }
  const requiresReview = lockPresent || tempFiles.length > 0 ||
    store.status !== "VALID" || backup.status === "INVALID" ||
    (backup.status === "VALID" && store.status === "VALID" &&
      (backup.entries > store.entries ||
        (backup.entries === store.entries && backup.sha256 !== store.sha256)));
  return Object.freeze({
    decision: requiresReview ? "HOLD_FOR_HUMAN_RECOVERY" : "NO_RECOVERY_ACTION_NEEDED",
    store: Object.freeze(store), backup: Object.freeze(backup), lockPresent,
    orphanTempCount: tempFiles.length,
    automaticRestoreAllowed: false,
    evidenceLimit: "LOCAL_CHECKS_NOT_TRUSTED_AUTHENTICITY"
  });
}
