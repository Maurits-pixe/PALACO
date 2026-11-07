import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { prepareRecoveryDossier } from "./recovery-dossier.mjs";
import { commitNonce, loadNonceStore } from "./nonce-store.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-recovery-dossier-"));
const nonceStorePath = join(dir, "reception-nonces.json");
const context = { citadelId: "LA-001", senderDeviceId: "sender", recipientDeviceId: "receiver" };
const manifest = { schema: "HARA_SYNC_MANIFEST_V1", ...context, nonce: "one",
  signature: "fake_signature_for_test" };
const outcome = { accepted: false, nonceCommitted: true, requiresHumanRecovery: true,
  reason: "WITNESS_CHANGED_DURING_COMMIT_HOLD" };
const run = (changes = {}) => prepareRecoveryDossier({ outcome, context, manifest,
  nonceStorePath, ...changes });
try {
  assert.equal((await run()).reason, "RECOVERY_NONCE_EVIDENCE_MISSING");
  await commitNonce(nonceStorePath, "LA-001", "LA-001:sender:one", 0);
  const first = await run();
  assert.equal(first.readyForHumanReview, true);
  assert.equal(first.decision, "HOLD");
  assert.equal(first.authorityGranted, false);
  assert.equal(first.contentReleased, false);
  assert.equal(first.dossier.nonceStoreRevisionObserved, 1);
  assert.equal(first.dossier.manifestReverified, false);
  assert.equal((await run()).dossier.dossierSha256, first.dossier.dossierSha256);
  assert.equal(JSON.stringify(first).includes("fake_signature_for_test"), false);
  assert.equal(JSON.stringify(first).includes("LA-001:sender:one"), false);
  assert.equal((await run({ manifest: { ...manifest, citadelId: "other" } })).reason,
    "RECOVERY_SCOPE_INVALID");
  assert.equal((await run({ manifest: { ...manifest, nonce: "absent" } })).reason,
    "RECOVERY_NONCE_EVIDENCE_MISSING");
  assert.equal((await run({ outcome: { ...outcome, nonceCommitted: false } })).reason,
    "RECOVERY_OUTCOME_NOT_ELIGIBLE");
  assert.equal((await run({ outcome: { ...outcome, reason: "UNEXPECTED" } })).reason,
    "RECOVERY_OUTCOME_NOT_ELIGIBLE");
  assert.equal((await run({ nonceStorePath: join(dir, "other.json") })).reason,
    "RECOVERY_NONCE_STORE_UNREADABLE");
  assert.equal((await loadNonceStore(nonceStorePath, "LA-001")).revision, 1);
  await writeFile(nonceStorePath, "not json");
  assert.equal((await run()).reason, "RECOVERY_NONCE_STORE_UNREADABLE");
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA read-only recovery dossier tests PASS");
