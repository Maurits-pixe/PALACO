import assert from "node:assert/strict";
import { emptyJournal, appendJournal } from "./journal.mjs";
import { compareSyncHistories } from "./sync-contract.mjs";

const ctx = { localDeviceId: "device_a", remoteDeviceId: "device_b", citadelId: "LA-001" };
const empty = emptyJournal("LA-001");
const one = appendJournal(empty, "RECEPTION", { eventId: "a", citadelId: "LA-001",
  actorRef: "opaque_a", arrivalAt: "2026-11-07T09:00:00Z" });
const two = appendJournal(one, "RECEPTION", { eventId: "b", citadelId: "LA-001",
  actorRef: "opaque_b", arrivalAt: "2026-11-07T09:01:00Z" });
const divergent = appendJournal(one, "RECEPTION", { eventId: "c", citadelId: "LA-001",
  actorRef: "opaque_c", arrivalAt: "2026-11-07T09:02:00Z" });
assert.equal(compareSyncHistories(one, one, ctx).verdict, "EQUAL");
assert.equal(compareSyncHistories(one, two, ctx).verdict, "LOCAL_BEHIND");
assert.equal(compareSyncHistories(two, one, ctx).verdict, "REMOTE_BEHIND");
const conflict = compareSyncHistories(two, divergent, ctx);
assert.equal(conflict.verdict, "CONFLICT_HOLD");
assert.equal(conflict.commonEntries, 1);
assert.equal(conflict.autoMergeAllowed, false);
assert.throws(() => compareSyncHistories(one, one, { ...ctx, remoteDeviceId: "device_a" }), /INVALID_SYNC_CONTEXT/);
assert.throws(() => compareSyncHistories(one, emptyJournal("OTHER"), ctx), /SYNC_SCOPE_MISMATCH/);
const tampered = JSON.parse(JSON.stringify(one));
tampered.entries[0].sequence = 4;
assert.throws(() => compareSyncHistories(tampered, one, ctx), /JOURNAL_SEQUENCE_INVALID/);
console.log("HARA sync preflight tests PASS");
