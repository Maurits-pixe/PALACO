import assert from "node:assert/strict";
import { emptyInbox, receiveReception, transition, unreadCount, badge } from "./index.mjs";

const a = { eventId: "visit-1", citadelId: "LA-001", actorRef: "visitor-pseudonym-1",
  arrivalAt: "2026-11-07T09:00:00Z" };
const b = { ...a, eventId: "visit-2", actorRef: "visitor-pseudonym-2" };
const first = receiveReception(emptyInbox(), a);
assert.equal(unreadCount(first), 1);
assert.equal(receiveReception(first, a), first);
assert.throws(() => receiveReception(first, { ...a, actorRef: "other" }), /EVENT_ID_COLLISION/);
const second = receiveReception(first, b);
assert.equal(badge(second).count, 2);
assert.equal(badge(second).label, "2 nieuwe berichten");
const cmd = { key: "LA-001:visit-1", changedAt: "2026-11-07T09:01:00Z",
  operatorRef: "authorized-reviewer", authorized: true, to: "READ" };
assert.throws(() => transition(second, { ...cmd, authorized: false }), /AUTHORIZATION_REQUIRED/);
assert.throws(() => transition(second, { ...cmd, to: "HANDLED" }), /INVALID_STATE_TRANSITION/);
const read = transition(second, cmd);
assert.equal(unreadCount(read), 1);
assert.equal(transition(read, cmd), read);
const handled = transition(read, { ...cmd, to: "HANDLED" });
assert.equal(handled.events[0].state, "HANDLED");
assert.throws(() => transition(handled, cmd), /INVALID_STATE_TRANSITION/);
assert.equal(unreadCount(second), 2); // immutable previous snapshot
assert.equal(badge(emptyInbox()).count, 0);
console.log("HARA reception inbox candidate: 12 assertions PASS");
