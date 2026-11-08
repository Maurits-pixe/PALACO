import { open, readFile } from "node:fs/promises";
import { dirname } from "node:path";
import { createHash } from "node:crypto";
import { replayJournal } from "./journal.mjs";

const hash = (value) => createHash("sha256").update(value).digest("hex");
const checkName = (path) => typeof path === "string" &&
  /reception-backup-[A-Za-z0-9_-]{1,64}\.json$/.test(path);

// Write-once checkpoint. No replace/rotate/delete operation is provided.
export async function createBackup(path, journal) {
  if (!checkName(path)) throw new TypeError("INVALID_BACKUP_PATH");
  const snapshot = replayJournal(journal);
  const payload = JSON.stringify(journal);
  const record = JSON.stringify({ schema: "HARA_BACKUP_V1", citadelId: journal.citadelId,
    entries: snapshot.revision, payload, sha256: hash(payload) });
  const file = await open(path, "wx", 0o600);
  try { await file.writeFile(record, "utf8"); await file.sync(); }
  finally { await file.close(); }
  const dir = await open(dirname(path), "r");
  try { await dir.sync(); }
  finally { await dir.close(); }
  return Object.freeze({ entries: snapshot.revision, sha256: hash(payload) });
}

// Read-only validation; never applies a restore or grants authority.
export async function inspectBackup(path, expectedCitadelId) {
  if (!checkName(path)) throw new TypeError("INVALID_BACKUP_PATH");
  let record;
  try { record = JSON.parse(await readFile(path, "utf8")); }
  catch { throw new Error("BACKUP_UNREADABLE"); }
  if (!record || record.schema !== "HARA_BACKUP_V1" ||
      record.citadelId !== expectedCitadelId ||
      typeof record.payload !== "string" || record.sha256 !== hash(record.payload)) {
    throw new Error("BACKUP_INTEGRITY_OR_SCOPE_FAILED");
  }
  let journal;
  try { journal = JSON.parse(record.payload); }
  catch { throw new Error("BACKUP_PAYLOAD_INVALID"); }
  if (journal.citadelId !== expectedCitadelId) throw new Error("BACKUP_SCOPE_FAILED");
  const inbox = replayJournal(journal);
  if (inbox.revision !== record.entries) throw new Error("BACKUP_REVISION_MISMATCH");
  return Object.freeze({ valid: true, entries: inbox.revision, citadelId: expectedCitadelId,
    sha256: record.sha256 });
}
