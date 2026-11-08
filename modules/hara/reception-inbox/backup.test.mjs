import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { emptyJournal, appendJournal } from "./journal.mjs";
import { createBackup, inspectBackup } from "./backup.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-backup-"));
const file = join(dir, "reception-backup-001.json");
const journal = appendJournal(emptyJournal("LA-001"), "RECEPTION", {
  eventId: "arrival_1", citadelId: "LA-001", actorRef: "opaque_1",
  arrivalAt: "2026-11-07T09:00:00Z" });
const result = await createBackup(file, journal);
assert.equal(result.entries, 1);
assert.equal((await inspectBackup(file, "LA-001")).valid, true);
await assert.rejects(createBackup(file, journal), { code: "EEXIST" });
await assert.rejects(inspectBackup(file, "OTHER"), /BACKUP_INTEGRITY_OR_SCOPE_FAILED/);
const raw = await readFile(file, "utf8");
await writeFile(file, raw.replace("opaque_1", "tampered"));
await assert.rejects(inspectBackup(file, "LA-001"), /BACKUP_INTEGRITY_OR_SCOPE_FAILED/);
await assert.rejects(createBackup(join(dir, "uncontrolled.json"), journal), /INVALID_BACKUP_PATH/);
console.log("HARA write-once backup tests PASS");
