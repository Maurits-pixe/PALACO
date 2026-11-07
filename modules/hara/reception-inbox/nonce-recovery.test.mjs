import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { commitNonce } from "./nonce-store.mjs";
import { inspectNonceRecovery } from "./nonce-recovery.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-recovery-"));
const file = join(dir, "reception-nonces.json");
const anchor = { minimumRevision: 1, requiredNonces: ["LA-001:sender_1:nonce_1"] };
const check = (a = anchor) => inspectNonceRecovery(file, "LA-001", a);
try {
  const missing = await check();
  assert.equal(missing.safeToProceed, false);
  assert.ok(missing.issues.includes("REVISION_ROLLBACK_SUSPECTED"));
  assert.ok(missing.issues.includes("ANCHORED_NONCE_MISSING"));

  await commitNonce(file, "LA-001", anchor.requiredNonces[0], 0);
  const clean = await check();
  assert.equal(clean.reason, "CLEAN_WITH_SUPPLIED_ANCHOR");
  assert.equal(clean.inspectionClean, true);
  assert.equal(clean.safeToProceed, false);
  assert.equal(clean.revision, 1);
  assert.equal(clean.authorityGranted, false);
  assert.equal(clean.rollbackResistanceEstablished, false);

  await writeFile(file + ".lock", "stale", "utf8");
  assert.ok((await check()).issues.includes("WRITER_LOCK_PRESENT"));
  await unlink(file + ".lock");

  const orphan = join(dir, ".reception-nonces-abandoned.tmp");
  await writeFile(orphan, "partial", "utf8");
  assert.ok((await check()).issues.includes("ORPHAN_TEMP_PRESENT"));
  await unlink(orphan);

  const missingNonce = await check({ minimumRevision: 1,
    requiredNonces: ["LA-001:sender_1:nonce_missing"] });
  assert.ok(missingNonce.issues.includes("ANCHORED_NONCE_MISSING"));

  await writeFile(file, "corrupt", "utf8");
  assert.equal((await check()).reason, "STORE_UNREADABLE_HOLD");
  assert.equal((await check()).safeToProceed, false);
  assert.equal((await check({ minimumRevision: -1, requiredNonces: [] })).reason,
    "RECOVERY_INPUT_INVALID");
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA nonce recovery tests PASS");
