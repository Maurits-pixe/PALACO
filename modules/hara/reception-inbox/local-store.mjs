import { open, readFile, rename, unlink, mkdir } from "node:fs/promises";
import { dirname, basename, join } from "node:path";
import { randomUUID, createHash } from "node:crypto";
import { emptyJournal, replayJournal } from "./journal.mjs";

const digest = (data) => createHash("sha256").update(data).digest("hex");
const validPath = (path) => typeof path === "string" && path.length > 1 &&
  basename(path) === "reception-journal.json";

async function loadRaw(path) {
  try { return await readFile(path, "utf8"); }
  catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

export async function loadLocalJournal(path, citadelId) {
  if (!validPath(path)) throw new TypeError("INVALID_STORE_PATH");
  const raw = await loadRaw(path);
  if (raw === null) return emptyJournal(citadelId);
  let envelope;
  try { envelope = JSON.parse(raw); }
  catch { throw new Error("STORE_CORRUPT_JSON"); }
  if (!envelope || envelope.schema !== "HARA_LOCAL_STORE_V1" ||
      typeof envelope.payload !== "string" ||
      envelope.sha256 !== digest(envelope.payload)) throw new Error("STORE_INTEGRITY_FAILED");
  let journal;
  try { journal = JSON.parse(envelope.payload); }
  catch { throw new Error("STORE_CORRUPT_JOURNAL"); }
  if (journal.citadelId !== citadelId) throw new Error("STORE_SCOPE_MISMATCH");
  replayJournal(journal);
  return journal;
}

// Single-host candidate only. Lock files are deliberately not auto-broken:
// a crash requires supervised recovery, never silent writer takeover.
export async function saveLocalJournal(path, journal, expectedEntries) {
  if (!validPath(path) || !Number.isSafeInteger(expectedEntries) || expectedEntries < 0) {
    throw new TypeError("INVALID_STORE_ARGUMENTS");
  }
  replayJournal(journal);
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const lockPath = path + ".lock";
  let lock;
  try { lock = await open(lockPath, "wx", 0o600); }
  catch (error) {
    if (error?.code === "EEXIST") throw new Error("STORE_WRITER_LOCKED");
    throw error;
  }
  let tempPath;
  try {
    const previous = await loadLocalJournal(path, journal.citadelId);
    if (previous.entries.length !== expectedEntries) throw new Error("STORE_STALE_REVISION");
    if (journal.entries.length < expectedEntries) throw new Error("STORE_ROLLBACK_DENIED");
    // Preserve the existing append-only prefix; sequence lengths alone are insufficient.
    if (JSON.stringify(journal.entries.slice(0, expectedEntries)) !==
        JSON.stringify(previous.entries)) throw new Error("STORE_HISTORY_REWRITE_DENIED");
    const payload = JSON.stringify(journal);
    const envelope = JSON.stringify({ schema: "HARA_LOCAL_STORE_V1", payload, sha256: digest(payload) });
    tempPath = join(dirname(path), ".reception-journal-" + randomUUID() + ".tmp");
    const handle = await open(tempPath, "wx", 0o600);
    try { await handle.writeFile(envelope, "utf8"); await handle.sync(); }
    finally { await handle.close(); }
    await rename(tempPath, path);
    tempPath = undefined;
    const directory = await open(dirname(path), "r");
    try { await directory.sync(); }
    finally { await directory.close(); }
    return { entries: journal.entries.length, sha256: digest(payload) };
  } finally {
    if (tempPath) await unlink(tempPath).catch(() => {});
    await lock.close();
    await unlink(lockPath);
  }
}
