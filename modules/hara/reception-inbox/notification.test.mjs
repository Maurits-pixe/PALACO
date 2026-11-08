import assert from "node:assert/strict";
import { emptyInbox, receiveReception, transition } from "./index.mjs";
import { indicator, pushIntent } from "./notification.mjs";

const event = (eventId, citadelId, actorRef) => ({
  eventId, citadelId, actorRef, arrivalAt: "2026-11-07T09:00:00Z"
});
let inbox = emptyInbox();
assert.equal(indicator(inbox, "LA-001").count, 0);
assert.equal(pushIntent(inbox, "LA-001", 0), null);
inbox = receiveReception(inbox, event("one", "LA-001", "private-pseudonym"));
assert.equal(indicator(inbox, "LA-001").count, 1);
assert.equal(indicator(inbox, "OTHER").count, 0);
const intent = pushIntent(inbox, "LA-001", 0);
assert.equal(intent?.unreadCount, 1);
assert.equal(intent?.requiresAuthorizedFetch, true);
assert.ok(!JSON.stringify(intent).includes("private-pseudonym"));
assert.ok(!JSON.stringify(intent).includes("one"));
assert.equal(pushIntent(inbox, "LA-001", 1), null);
inbox = receiveReception(inbox, event("two", "LA-001", "second-pseudonym"));
assert.equal(indicator(inbox, "LA-001").count, 2);
const read = transition(inbox, {
  key: "LA-001:one", changedAt: "2026-11-07T09:01:00Z",
  operatorRef: "reviewer", authorized: true, to: "READ"
});
assert.equal(indicator(read, "LA-001").count, 1);
assert.equal(pushIntent(read, "LA-001", 2), null);
assert.throws(() => indicator(inbox, "../OTHER"), /INVALID_CITADEL_SCOPE/);
assert.throws(() => pushIntent(inbox, "LA-001", -1), /INVALID_PREVIOUS_COUNT/);
console.log("Reception projection tests PASS");
