import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile, open, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { emptyJournal, appendJournal } from "./journal.mjs";
import { loadLocalJournal, saveLocalJournal } from "./local-store.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-store-"));
const path = join(dir, "reception-journal.json");
const initial = emptyJournal("LA-001");
assert.equal((await loadLocalJournal(path, "LA-001")).entries.length, 0);
await saveLocalJournal(path, initial, 0);
const entry = { eventId: "visit1", citadelId: "LA-001", actorRef: "opaque1",
  arrivalAt: "2026-11-07T09:00:00Z" };
const one = appendJournal(initial, "RECEPTION", entry);
await saveLocalJournal(path, one, 0);
assert.equal((await loadLocalJournal(path, "LA-001")).entries.length, 1);
await assert.rejects(saveLocalJournal(path, one, 0), /STORE_STALE_REVISION/);
await assert.rejects(saveLocalJournal(path, initial, 1), /STORE_ROLLBACK_DENIED/);
await assert.rejects(loadLocalJournal(path, "OTHER"), /STORE_SCOPE_MISMATCH/);
const lock = await open(path + ".lock", "wx");
try { await assert.rejects(saveLocalJournal(path, one, 1), /STORE_WRITER_LOCKED/); }
finally { await lock.close(); await unlink(path + ".lock"); }
const stored = await readFile(path, "utf8");
await writeFile(path, stored.replace("opaque1", "tampered"));
await assert.rejects(loadLocalJournal(path, "LA-001"), /STORE_INTEGRITY_FAILED/);
console.log("HARA local atomic-store tests PASS");
