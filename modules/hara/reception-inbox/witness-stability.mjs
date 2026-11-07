import { inspectExternalWitness } from "./witness-adapter.mjs";

const denied = (reason) => Object.freeze({ stable: false, reason,
  authorityGranted: false, safeToProceed: false, contentReleased: false });

// Two reads bracket verification, detecting changed snapshots within a bounded
// window. This is not an atomic, linearizable or independent witness proof.
export async function inspectStableWitness({ client, timeoutMs = 1500, ...options } = {}) {
  if (!client || typeof client.getLatestCheckpoint !== "function" ||
      !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 5000) {
    return denied("STABILITY_INPUT_INVALID");
  }
  let firstSnapshot;
  const firstClient = { getLatestCheckpoint: async (request) => {
    const received = await client.getLatestCheckpoint(request);
    // Snapshot primitives immediately; a client must not rewrite the first read.
    firstSnapshot = received ? structuredClone(received) : received;
    return received;
  } };
  const preflight = await inspectExternalWitness({ ...options, client: firstClient, timeoutMs });
  if (!preflight.evidenceChecked) return denied("STABILITY_FIRST_READ_HOLD_" + preflight.reason);

  const controller = new AbortController();
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => { controller.abort(); resolve({ kind: "timeout" }); }, timeoutMs);
  });
  let second;
  try {
    second = await Promise.race([
      Promise.resolve().then(() => client.getLatestCheckpoint({
        citadelId: options.citadelId, witnessId: options.pinnedWitnessId,
        signal: controller.signal
      })).then((value) => ({ kind: "data", value }), () => ({ kind: "error" })),
      timeout
    ]);
  } finally { clearTimeout(timer); controller.abort(); }
  if (second.kind === "timeout") return denied("STABILITY_SECOND_TIMEOUT_HOLD");
  if (second.kind !== "data" || !second.value) return denied("STABILITY_SECOND_UNAVAILABLE_HOLD");

  const a = firstSnapshot, b = second.value;
  if (!a || !a.checkpoint || !b.checkpoint ||
      !Number.isSafeInteger(a.sequenceFloor) ||
      !Number.isSafeInteger(b.sequenceFloor) ||
      a.sequenceFloor !== b.sequenceFloor ||
      a.checkpoint.signature !== b.checkpoint.signature ||
      a.checkpoint.sequence !== b.checkpoint.sequence ||
      a.checkpoint.minimumRevision !== b.checkpoint.minimumRevision ||
      a.checkpoint.prefixSha256 !== b.checkpoint.prefixSha256 ||
      a.checkpoint.citadelId !== b.checkpoint.citadelId ||
      a.checkpoint.witnessId !== b.checkpoint.witnessId) {
    return denied("STABILITY_SNAPSHOT_CHANGED_HOLD");
  }
  return Object.freeze({ stable: true, reason: "WITNESS_DOUBLE_READ_CONSISTENT_ONLY",
    witnessSequence: preflight.witnessSequence,
    authorityGranted: false, safeToProceed: false, contentReleased: false });
}
