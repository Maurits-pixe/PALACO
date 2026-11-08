import { emptyInbox, receiveReception, transition, assertInbox } from "./index.mjs";

export const JOURNAL_SCHEMA = "HARA_RECEPTION_JOURNAL_V1";
const plain = (x) => x && typeof x === "object" && !Array.isArray(x);

export function emptyJournal(citadelId) {
  if (typeof citadelId !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(citadelId)) {
    throw new TypeError("INVALID_CITADEL_SCOPE");
  }
  return Object.freeze({ schema: JOURNAL_SCHEMA, citadelId, entries: Object.freeze([]) });
}

function applyEntry(inbox, entry, citadelId) {
  if (!plain(entry) || !plain(entry.payload)) throw new TypeError("INVALID_JOURNAL_ENTRY");
  if (entry.kind === "RECEPTION") {
    if (entry.payload.citadelId !== citadelId) throw new Error("CROSS_CITADEL_ENTRY");
    return receiveReception(inbox, entry.payload);
  }
  if (entry.kind === "TRANSITION") {
    if (typeof entry.payload.key !== "string" ||
        !entry.payload.key.startsWith(citadelId + ":")) throw new Error("CROSS_CITADEL_ENTRY");
    // Authorization was verified when this command was first committed;
    // replay reconstructs history only. This is never a live authorization path.
    return transition(inbox, { ...entry.payload, authorized: true });
  }
  throw new Error("UNKNOWN_JOURNAL_KIND");
}

export function replayJournal(journal) {
  if (!plain(journal) || journal.schema !== JOURNAL_SCHEMA ||
      typeof journal.citadelId !== "string" ||
      !/^[A-Za-z0-9_-]{1,64}$/.test(journal.citadelId) ||
      !Array.isArray(journal.entries) || journal.entries.length > 20000) {
    throw new TypeError("INVALID_JOURNAL");
  }
  let inbox = emptyInbox();
  for (const [index, entry] of journal.entries.entries()) {
    if (!plain(entry) || entry.sequence !== index + 1 ||
        entry.previousRevision !== inbox.revision) throw new Error("JOURNAL_SEQUENCE_INVALID");
    const next = applyEntry(inbox, entry, journal.citadelId);
    if (next.revision !== inbox.revision + 1) throw new Error("JOURNAL_DUPLICATE_OR_NOOP");
    inbox = next;
  }
  assertInbox(inbox);
  return inbox;
}

export function appendJournal(journal, kind, payload) {
  const inbox = replayJournal(journal);
  const canonicalPayload = kind === "TRANSITION" && plain(payload)
    ? { key: payload.key, changedAt: payload.changedAt,
        operatorRef: payload.operatorRef, to: payload.to }
    : kind === "RECEPTION" && plain(payload)
      ? { eventId: payload.eventId, citadelId: payload.citadelId,
          actorRef: payload.actorRef, arrivalAt: payload.arrivalAt }
      : payload;
  if (kind === "TRANSITION" && payload?.authorized !== true) {
    throw new Error("AUTHORIZATION_REQUIRED");
  }
  const next = applyEntry(inbox, { kind, payload: canonicalPayload }, journal.citadelId);
  if (next.revision !== inbox.revision + 1) throw new Error("JOURNAL_DUPLICATE_OR_NOOP");
  const entry = Object.freeze({ sequence: journal.entries.length + 1,
    previousRevision: inbox.revision, kind, payload: Object.freeze({ ...canonicalPayload }) });
  return Object.freeze({ schema: JOURNAL_SCHEMA, citadelId: journal.citadelId,
    entries: Object.freeze([...journal.entries, entry]) });
}
