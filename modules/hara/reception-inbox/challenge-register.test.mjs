import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile, open, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { consumeReviewerChallenge, loadChallengeRegister } from "./challenge-register.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-challenge-"));
const path = join(dir, "reviewer-challenges.json");
const consume = (challenge, revision) => consumeReviewerChallenge(path, "LA-001",
  "PALACO_ONE_TEST", challenge, revision);
try {
  assert.equal((await loadChallengeRegister(path, "LA-001")).revision, 0);
  const first = await consume("challenge_1", 0);
  assert.equal(first.committed, true);
  assert.equal(first.authorityGranted, false);
  assert.equal((await loadChallengeRegister(path, "LA-001")).revision, 1);
  await assert.rejects(consume("challenge_1", 1), /CHALLENGE_REPLAY_DENIED/);
  await assert.rejects(consume("challenge_2", 0), /CHALLENGE_STALE_REVISION/);
  const outcomes = await Promise.allSettled([consume("challenge_2", 1), consume("challenge_2", 1)]);
  assert.equal(outcomes.filter((r) => r.status === "fulfilled").length, 1);
  assert.equal((await loadChallengeRegister(path, "LA-001")).revision, 2);
  assert.equal((await readFile(path, "utf8")).includes("challenge_1"), false);
  const lock = await open(path + ".lock", "wx");
  try { await assert.rejects(consume("challenge_3", 2), /CHALLENGE_WRITER_LOCKED/); }
  finally { await lock.close(); await rm(path + ".lock"); }
  await assert.rejects(loadChallengeRegister(path, "OTHER"), /CHALLENGE_REGISTER_INVALID_STATE/);
  await writeFile(path, "bad json");
  await assert.rejects(loadChallengeRegister(path, "LA-001"), /CHALLENGE_REGISTER_CORRUPT/);
  await assert.rejects(consume("challenge_3", 2), /CHALLENGE_REGISTER_CORRUPT/);
  await assert.rejects(consumeReviewerChallenge(path, "LA-001", "bad issuer", "one", 0),
    /CHALLENGE_CONSUME_INPUT_INVALID/);
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA durable challenge register tests PASS");
