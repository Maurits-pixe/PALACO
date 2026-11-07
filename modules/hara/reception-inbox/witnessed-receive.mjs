import { inspectStableWitness } from "./witness-stability.mjs";
import { receiveManifestPreflight } from "./receive-gate.mjs";

const hold = (reason, nonceCommitted = false) => Object.freeze({
  accepted: false, reason, nonceCommitted, authorityGranted: false,
  contentReleased: false, requiresHumanRecovery: nonceCommitted
});

// A composition test candidate: no protected content is ever released.
// Once committed, a nonce is intentionally NOT rolled back on later HOLD.
export async function witnessedReceivePreflight({ client, nonceStorePath, manifest,
  journal, context, trustSnapshot, anchor, anchorPublicKey,
  witnessPublicKey, pinnedWitnessId, trustedSequenceFloor,
  now, timeoutMs = 1500 } = {}) {
  const sightings = [];
  const observedClient = client && typeof client.getLatestCheckpoint === "function" ? {
    getLatestCheckpoint: async (request) => {
      const snapshot = await client.getLatestCheckpoint(request);
      if (snapshot?.checkpoint) sightings.push({
        sequenceFloor: snapshot.sequenceFloor,
        sequence: snapshot.checkpoint.sequence,
        signature: snapshot.checkpoint.signature
      });
      return snapshot;
    }
  } : null;
  const check = () => inspectStableWitness({ client: observedClient,
    path: nonceStorePath, citadelId: context?.citadelId, anchor,
    anchorPublicKey, witnessPublicKey, pinnedWitnessId,
    trustedSequenceFloor, now, timeoutMs });
  const before = await check();
  if (!before.stable) return hold("WITNESS_BEFORE_COMMIT_HOLD");
  if (sightings.length !== 2) return hold("WITNESS_BEFORE_COMMIT_AMBIGUOUS");
  const initial = { ...sightings[1] };

  const receive = await receiveManifestPreflight({ manifest, journal, context,
    trustSnapshot, nonceStorePath });
  if (!receive.accepted || !receive.nonceCommitted) {
    return hold("NONCE_COMMIT_PRECHECK_DENIED");
  }
  const after = await check();
  if (!after.stable || sightings.length !== 4) {
    return hold("WITNESS_AFTER_COMMIT_HOLD", true);
  }
  const final = sightings[3];
  if (initial.sequenceFloor !== final.sequenceFloor ||
      initial.sequence !== final.sequence || initial.signature !== final.signature) {
    return hold("WITNESS_CHANGED_DURING_COMMIT_HOLD", true);
  }
  return Object.freeze({ accepted: true, reason: "WITNESSED_NONCE_PRECHECK_ONLY",
    nonceCommitted: true, nonceRevision: receive.nonceRevision,
    authorityGranted: false, contentReleased: false, requiresHumanRecovery: false });
}
