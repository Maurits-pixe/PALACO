import { replayJournal } from "./journal.mjs";

const validId = (value) => typeof value === "string" &&
  /^[A-Za-z0-9_-]{1,64}$/.test(value);

// Read-only preflight. It does not transmit, merge, authenticate or apply data.
export function compareSyncHistories(local, remote, context) {
  if (!context || !validId(context.localDeviceId) || !validId(context.remoteDeviceId) ||
      context.localDeviceId === context.remoteDeviceId ||
      !validId(context.citadelId)) throw new TypeError("INVALID_SYNC_CONTEXT");
  if (!local || !remote || local.citadelId !== context.citadelId ||
      remote.citadelId !== context.citadelId) throw new Error("SYNC_SCOPE_MISMATCH");
  replayJournal(local);
  replayJournal(remote);
  const common = Math.min(local.entries.length, remote.entries.length);
  for (let i = 0; i < common; i += 1) {
    if (JSON.stringify(local.entries[i]) !== JSON.stringify(remote.entries[i])) {
      return Object.freeze({ verdict: "CONFLICT_HOLD", commonEntries: i,
        localEntries: local.entries.length, remoteEntries: remote.entries.length,
        autoMergeAllowed: false, nextAction: "HUMAN_REVIEW" });
    }
  }
  const verdict = local.entries.length === remote.entries.length ? "EQUAL" :
    local.entries.length < remote.entries.length ? "LOCAL_BEHIND" : "REMOTE_BEHIND";
  return Object.freeze({ verdict, commonEntries: common,
    localEntries: local.entries.length, remoteEntries: remote.entries.length,
    autoMergeAllowed: false,
    nextAction: verdict === "EQUAL" ? "NONE" : "AUTHORIZED_REPLICATION_REQUIRED" });
}
