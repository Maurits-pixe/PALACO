// HARA/HARAM reception inbox candidate. No network, device push, or authority effects.
const STATES = new Set(["UNREAD", "READ", "HANDLED"]);
const MAX_ITEMS = 10000;
const validText = (v, max = 128) => typeof v === "string" && v.length > 0 && v.length <= max;
const validId = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const frozen = (value) => Object.freeze(value);

export function emptyInbox() {
  return frozen({ revision: 0, events: frozen([]) });
}

export function unreadCount(inbox) {
  return inbox.events.filter((event) => event.state === "UNREAD").length;
}

export function receiveReception(inbox, input) {
  assertInbox(inbox);
  if (!input || !validId(input.eventId) || !validId(input.citadelId) ||
      !validText(input.arrivalAt, 64) || !validText(input.actorRef)) {
    throw new TypeError("INVALID_RECEPTION_ENVELOPE");
  }
  // Event IDs are scoped to a Citadel, not to a user's display name.
  const key = input.citadelId + ":" + input.eventId;
  const prior = inbox.events.find((event) => event.key === key);
  if (prior) {
    if (prior.actorRef !== input.actorRef || prior.arrivalAt !== input.arrivalAt) {
      throw new Error("EVENT_ID_COLLISION");
    }
    return inbox; // at-least-once transport cannot inflate the badge
  }
  if (inbox.events.length >= MAX_ITEMS) throw new Error("INBOX_CAPACITY_REACHED");
  const event = frozen({
    key, eventId: input.eventId, citadelId: input.citadelId,
    actorRef: input.actorRef, arrivalAt: input.arrivalAt,
    state: "UNREAD", stateChangedAt: input.arrivalAt
  });
  return frozen({ revision: inbox.revision + 1, events: frozen([...inbox.events, event]) });
}

export function transition(inbox, command) {
  assertInbox(inbox);
  if (!command || !validText(command.key, 257) || !validText(command.changedAt, 64) ||
      !validText(command.operatorRef) || !["READ", "HANDLED"].includes(command.to)) {
    throw new TypeError("INVALID_TRANSITION");
  }
  // Authorization belongs to a verified host session; never infer it here.
  if (command.authorized !== true) throw new Error("AUTHORIZATION_REQUIRED");
  const index = inbox.events.findIndex((event) => event.key === command.key);
  if (index < 0) throw new Error("EVENT_NOT_FOUND");
  const current = inbox.events[index];
  if (current.state === command.to) return inbox;
  if (current.state === "HANDLED" || (current.state === "UNREAD" && command.to === "HANDLED")) {
    throw new Error("INVALID_STATE_TRANSITION");
  }
  const next = inbox.events.slice();
  next[index] = frozen({ ...current, state: command.to, stateChangedAt: command.changedAt });
  return frozen({ revision: inbox.revision + 1, events: frozen(next) });
}

export function assertInbox(inbox) {
  if (!inbox || !Number.isSafeInteger(inbox.revision) || inbox.revision < 0 ||
      !Array.isArray(inbox.events) || inbox.events.some((event) => !STATES.has(event.state))) {
    throw new TypeError("INVALID_INBOX");
  }
}

export function badge(inbox) {
  const count = unreadCount(inbox);
  return frozen({ count, label: count === 0 ? "Geen nieuwe berichten" :
    count === 1 ? "1 nieuw bericht" : count + " nieuwe berichten" });
}

