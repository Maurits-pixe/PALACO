import { inspectWitnessedAnchor } from "./anchor-witness.mjs";

const denied = (reason) => Object.freeze({ evidenceChecked: false, reason,
  authorityGranted: false, safeToProceed: false, contentReleased: false });

// An injected read-only witness client is supplied by a separate integration.
// There is intentionally no default URL, network transport, credential or key.
export async function inspectExternalWitness({ client, path, citadelId, anchor,
  anchorPublicKey, witnessPublicKey, pinnedWitnessId, trustedSequenceFloor,
  now, timeoutMs = 1500 } = {}) {
  if (!client || typeof client.getLatestCheckpoint !== "function" ||
      !Number.isSafeInteger(trustedSequenceFloor) || trustedSequenceFloor < 0 ||
      !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 5000 ||
      !Number.isSafeInteger(now)) return denied("WITNESS_ADAPTER_INPUT_INVALID");

  const abort = new AbortController();
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => { abort.abort(); resolve({ kind: "timeout" }); }, timeoutMs);
  });
  let response;
  try {
    response = await Promise.race([
      Promise.resolve().then(() => client.getLatestCheckpoint({
        citadelId, witnessId: pinnedWitnessId, signal: abort.signal
      })).then((value) => ({ kind: "data", value }), () => ({ kind: "error" })),
      timeout
    ]);
  } finally { clearTimeout(timer); abort.abort(); }
  if (response.kind === "timeout") return denied("WITNESS_TIMEOUT_HOLD");
  if (response.kind !== "data" || !response.value) return denied("WITNESS_UNAVAILABLE_HOLD");
  if (!Object.hasOwn(response.value, "checkpoint") ||
      !Object.hasOwn(response.value, "sequenceFloor") ||
      !Number.isSafeInteger(response.value.sequenceFloor) ||
      response.value.sequenceFloor < trustedSequenceFloor) return denied("WITNESS_FLOOR_CONFLICT_HOLD");

  // A remote floor is advisory until authenticated by an independent channel.
  // Both the external floor and separately supplied floor must be satisfied.
  const checkpoint = response.value.checkpoint;
  if (!checkpoint || checkpoint.sequence < response.value.sequenceFloor) {
    return denied("WITNESS_CHECKPOINT_STALE_HOLD");
  }
  const inspected = await inspectWitnessedAnchor({ path, citadelId, anchor,
    anchorPublicKey, witness: checkpoint, witnessPublicKey, pinnedWitnessId,
    minimumWitnessSequence: Math.max(trustedSequenceFloor, response.value.sequenceFloor), now });
  if (!inspected.witnessed) return denied("WITNESS_PROOF_DENIED_" + inspected.reason);
  return Object.freeze({ evidenceChecked: true, reason: "WITNESS_EVIDENCE_CONSISTENT_ONLY",
    witnessSequence: inspected.witnessSequence,
    authorityGranted: false, safeToProceed: false, contentReleased: false });
}
