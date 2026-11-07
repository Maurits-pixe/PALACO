import assert from "node:assert/strict";
import { mkdtemp, open, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { emptyJournal, appendJournal } from "./journal.mjs";
import { saveLocalJournal } from "./local-store.mjs";
import { createBackup } from "./backup.mjs";
import { inspectRecovery } from "./recovery.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-recovery-"));
const storePath = join(dir, "reception-journal.json");
const backupPath = join(dir, "reception-backup-001.json");
const args = { storePath, backupPath, citadelId: "LA-001" };
assert.equal((await inspectRecovery(args)).decision, "HOLD_FOR_HUMAN_RECOVERY");
let journal = emptyJournal("LA-001");
await saveLocalJournal(storePath, journal, 0);
assert.equal((await inspectRecovery({ storePath, citadelId: "LA-001" })).decision,
  "NO_RECOVERY_ACTION_NEEDED");
journal = appendJournal(journal, "RECEPTION", {
  eventId: "arrival_1", citadelId: "LA-001", actorRef: "opaque_1",
  arrivalAt: "2026-11-07T09:00:00Z" });
await createBackup(backupPath, journal);
assert.equal((await inspectRecovery(args)).decision, "HOLD_FOR_HUMAN_RECOVERY");
await saveLocalJournal(storePath, journal, 0);
assert.equal((await inspectRecovery(args)).decision, "NO_RECOVERY_ACTION_NEEDED");
const lock = await open(storePath + ".lock", "wx");
try { assert.equal((await inspectRecovery(args)).lockPresent, true); }
finally { await lock.close(); await unlink(storePath + ".lock"); }
const temp = join(dir, ".reception-journal-1234.tmp");
await writeFile(temp, "interrupted");
assert.equal((await inspectRecovery(args)).orphanTempCount, 1);
await unlink(temp);
assert.equal((await inspectRecovery(args)).automaticRestoreAllowed, false);
console.log("HARA read-only recovery tests PASS");
