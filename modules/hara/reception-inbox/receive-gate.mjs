import { loadNonceStore, commitNonce } from "./nonce-store.mjs";
import { inspectAndReserve } from "./trust-gate.mjs";

const denied = (reason) => Object.freeze({ accepted: false, reason,
  nonceCommitted: false, authorityGranted: false, contentReleased: false });

// A preflight receipt, NOT an authorization or a content delivery endpoint.
// The trust snapshot must be independently pinned and fresh; this route cannot
// establish device enrollment, global ordering, or rollback-resistant storage.
export async function receiveManifestPreflight({ manifest, journal, context,
  trustSnapshot, nonceStorePath } = {}) {
  if (typeof nonceStorePath !== "string" || !context ||
      !Array.isArray(trustSnapshot)) return denied("RECEIVE_INPUT_INVALID");
  if (manifest?.citadelId !== context.citadelId ||
      journal?.citadelId !== context.citadelId) return denied("SCOPE_DENIED");
  let nonceState;
  try { nonceState = await loadNonceStore(nonceStorePath, context.citadelId); }
  catch { return denied("NONCE_STORE_UNAVAILABLE"); }

  let proposed;
  try {
    proposed = inspectAndReserve(manifest, journal, context,
      trustSnapshot, nonceState.consumed);
  } catch { return denied("PRECHECK_INVALID"); }
  if (!proposed.accepted) return denied(proposed.reason);

  // Derive the key from the verified scope, never from a caller-supplied key.
  const nonceKey = `${context.citadelId}:${context.senderDeviceId}:${manifest.nonce}`;
  if (proposed.nextNonces.length !== nonceState.consumed.length + 1 ||
      proposed.nextNonces.at(-1) !== nonceKey) return denied("RESERVATION_MISMATCH");
  let committed;
  try {
    committed = await commitNonce(nonceStorePath, context.citadelId,
      nonceKey, nonceState.revision);
  } catch { return denied("NONCE_COMMIT_DENIED"); }

  return Object.freeze({ accepted: true, reason: "NONCE_COMMITTED_PRECHECK_ONLY",
    nonceCommitted: committed.committed === true,
    nonceRevision: committed.revision,
    authorityGranted: false, contentReleased: false });
}
