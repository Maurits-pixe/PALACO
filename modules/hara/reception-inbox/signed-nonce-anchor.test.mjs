import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, rm, writeFile, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { commitNonce, loadNonceStore } from "./nonce-store.mjs";
import { createNonceAnchor, inspectSignedNonceAnchor } from "./signed-nonce-anchor.mjs";

const keys = generateKeyPairSync("ed25519");
const other = generateKeyPairSync("ed25519");
const dir = await mkdtemp(join(tmpdir(), "hara-anchor-"));
const path = join(dir, "reception-nonces.json");
const inspect = (anchor, key = keys.publicKey, now = 1050) =>
  inspectSignedNonceAnchor(path, "LA-001", anchor, key, now);
try {
  await commitNonce(path, "LA-001", "LA-001:sender:one", 0);
  const oldFile = await readFile(path, "utf8");
  const anchor = createNonceAnchor("LA-001", await loadNonceStore(path, "LA-001"),
    { anchorId: "anchor_1", issuedAt: 1000, expiresAt: 1100 }, keys.privateKey);
  assert.equal((await inspect(anchor)).checked, true);
  assert.equal((await inspect(anchor)).safeToProceed, false);
  assert.equal((await inspect(anchor)).antiRollbackEstablished, false);
  assert.equal((await inspect(anchor, other.publicKey)).reason, "ANCHOR_SIGNATURE_DENIED");
  assert.equal((await inspect({ ...anchor, revision: 0 })).reason, "ANCHOR_SIGNATURE_DENIED");
  assert.equal((await inspect(anchor, keys.publicKey, 1100)).reason, "ANCHOR_CONTEXT_DENIED");
  await commitNonce(path, "LA-001", "LA-001:sender:two", 1);
  assert.equal((await inspect(anchor)).checked, true);
  const newer = createNonceAnchor("LA-001", await loadNonceStore(path, "LA-001"),
    { anchorId: "anchor_2", issuedAt: 1000, expiresAt: 1100 }, keys.privateKey);
  await writeFile(path, oldFile, "utf8");
  assert.equal((await inspect(newer)).reason, "ANCHOR_REVISION_ROLLBACK");
  assert.equal((await inspect(anchor)).checked, true); // stale-but-valid anchor cannot detect rollback
  await commitNonce(path, "LA-001", "LA-001:sender:changed", 1);
  assert.equal((await inspect(newer)).reason, "ANCHOR_PREFIX_MISMATCH");
  await writeFile(path + ".lock", "stale", "utf8");
  assert.equal((await inspect(anchor)).reason, "ANCHOR_RECOVERY_HOLD");
  await writeFile(path, "corrupt", "utf8");
  assert.equal((await inspect(anchor)).reason, "ANCHOR_STORE_UNAVAILABLE");
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA signed nonce anchor tests PASS");
