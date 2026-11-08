import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { consumeReviewerChallenge } from "./challenge-register.mjs";
import { inspectChallengeRecovery } from "./challenge-recovery.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-challenge-recovery-"));
const path = join(dir, "reviewer-challenges.json");
const inspect = () => inspectChallengeRecovery({ path, citadelId: "LA-001" });
try {
  assert.equal((await inspect()).reason, "CHALLENGE_RECOVERY_STORE_MISSING");
  await consumeReviewerChallenge(path, "LA-001", "PALACO_ONE_TEST", "challenge_1", 0);
  const clean = await inspect();
  assert.equal(clean.reason, "CHALLENGE_RECOVERY_LOCAL_SNAPSHOT_ONLY");
  assert.equal(clean.observedRevision, 1);
  assert.equal(clean.safeToProceed, false);
  const temp = join(dir, ".reviewer-challenges-abandoned.tmp");
  await writeFile(temp, "partial");
  assert.equal((await inspect()).reason, "CHALLENGE_RECOVERY_TEMPORARY_FILES_PRESENT");
  await writeFile(path + ".lock", "stale");
  assert.equal((await inspect()).reason, "CHALLENGE_RECOVERY_WRITER_LOCK_PRESENT");
  await rm(path + ".lock");
  await rm(temp);
  await writeFile(path, "corrupt");
  assert.equal((await inspect()).reason, "CHALLENGE_RECOVERY_STORE_INVALID");
  await rm(path);
  await symlink(join(dir, "elsewhere"), path);
  assert.equal((await inspect()).reason, "CHALLENGE_RECOVERY_UNSAFE_FILE_TYPE");
  assert.equal((await inspectChallengeRecovery({ path, citadelId: "OTHER" })).safeToProceed, false);
  assert.equal((await inspectChallengeRecovery({ path: "wrong.json", citadelId: "LA-001" })).reason,
    "CHALLENGE_RECOVERY_SCOPE_INVALID");
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA read-only challenge recovery tests PASS");
