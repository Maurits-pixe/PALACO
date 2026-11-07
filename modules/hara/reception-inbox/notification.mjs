import { assertInbox, unreadCount } from "./index.mjs";

// UI projection: intentionally excludes actorRef, eventId and raw reception content.
export function indicator(inbox, citadelId) {
  assertInbox(inbox);
  if (typeof citadelId !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(citadelId)) {
    throw new TypeError("INVALID_CITADEL_SCOPE");
  }
  const relevant = inbox.events.filter((event) => event.citadelId === citadelId);
  const count = relevant.filter((event) => event.state === "UNREAD").length;
  return Object.freeze({
    count,
    accessibleLabel: count === 0 ? "Geen nieuwe receptieberichten" :
      count === 1 ? "1 nieuw receptiebericht" : count + " nieuwe receptieberichten",
    hasUnread: count > 0
  });
}

// Output is only an intent for a separately authorized delivery worker.
// Neither this function nor its caller should claim that push was delivered.
export function pushIntent(inbox, citadelId, previousUnreadCount) {
  const current = indicator(inbox, citadelId);
  if (!Number.isSafeInteger(previousUnreadCount) || previousUnreadCount < 0) {
    throw new TypeError("INVALID_PREVIOUS_COUNT");
  }
  if (current.count <= previousUnreadCount) return null;
  return Object.freeze({
    kind: "RECEPTION_BADGE_CHANGED",
    citadelId,
    unreadCount: current.count,
    title: "HARAM · Receptie",
    body: "Er zijn nieuwe receptieberichten.",
    // No names, VisitCards, locations, links, identity or evidence in push.
    requiresAuthorizedFetch: true
  });
}

// Aggregate counts must be scoped; this helper is for isolated diagnostics only.
export function diagnosticTotal(inbox) {
  assertInbox(inbox);
  return unreadCount(inbox);
}
