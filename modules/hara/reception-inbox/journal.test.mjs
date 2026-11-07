import assert from "node:assert/strict";
import { emptyJournal, appendJournal, replayJournal } from "./journal.mjs";
import { unreadCount } from "./index.mjs";

const arrival = { eventId: "arrival_1", citadelId: "LA-001", actorRef: "opaque_1",
  arrivalAt: "2026-11-07T09:00:00Z" };
const initial = emptyJournal("LA-001");
const one = appendJournal(initial, "RECEPTION", arrival);
const minimized = appendJournal(initial, "RECEPTION", { ...arrival, visitorName: "DO_NOT_STORE" });
assert.equal(JSON.stringify(minimized).includes("DO_NOT_STORE"), false);
assert.equal(unreadCount(replayJournal(one)), 1);
assert.equal(unreadCount(replayJournal(JSON.parse(JSON.stringify(one)))), 1);
assert.throws(() => appendJournal(one, "RECEPTION", arrival), /JOURNAL_DUPLICATE_OR_NOOP/);
assert.throws(() => appendJournal(one, "RECEPTION", { ...arrival, citadelId: "OTHER" }), /CROSS_CITADEL_ENTRY/);
const changedAt = "2026-11-07T09:05:00Z";
const cmd = { key: "LA-001:arrival_1", changedAt, operatorRef: "reviewer_1",
  authorized: true, to: "READ" };
assert.throws(() => appendJournal(one, "TRANSITION", { ...cmd, authorized: false }), /AUTHORIZATION_REQUIRED/);
const two = appendJournal(one, "TRANSITION", cmd);
assert.equal(unreadCount(replayJournal(two)), 0);
assert.equal(two.entries[1].payload.authorized, undefined);
assert.throws(() => appendJournal(two, "TRANSITION", cmd), /JOURNAL_DUPLICATE_OR_NOOP/);
const tamper = JSON.parse(JSON.stringify(two));
tamper.entries[1].sequence = 9;
assert.throws(() => replayJournal(tamper), /JOURNAL_SEQUENCE_INVALID/);
const tamperScope = JSON.parse(JSON.stringify(two));
tamperScope.entries[0].payload.citadelId = "OTHER";
assert.throws(() => replayJournal(tamperScope), /CROSS_CITADEL_ENTRY/);
assert.equal(replayJournal(initial).revision, 0);
console.log("HARA offline journal tests PASS");
