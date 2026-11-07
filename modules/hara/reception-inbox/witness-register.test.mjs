import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createWitnessCheckpoint } from "./anchor-witness.mjs";
import { appendWitnessCheckpoint, loadWitnessRegister } from "./witness-register.mjs";

const keys = generateKeyPairSync("ed25519");
const wrong = generateKeyPairSync("ed25519");
const dir = await mkdtemp(join(tmpdir(), "hara-witness-register-"));
const path = join(dir, "witness-register.json");
const witnessId = "witness_1", citadelId = "LA-001";
const anchor = (revision, prefixSha256) => ({ schema: "HARA_NONCE_ANCHOR_V1",
  citadelId, revision, prefixSha256 });
const check = (sequence, revision, prefixSha256 = "a".repeat(64)) =>
  createWitnessCheckpoint(anchor(revision, prefixSha256), {
    witnessId, sequence, issuedAt: 1000, expiresAt: 1100 }, keys.privateKey);
const append = (checkpoint, expectedSequence, key = keys.publicKey) =>
  appendWitnessCheckpoint(path, citadelId, witnessId, checkpoint, key, 1050, expectedSequence);
const rejects = async (promise, reason) => assert.rejects(promise,
  (error) => error.message === reason);
try {
  assert.equal((await loadWitnessRegister(path, citadelId, witnessId)).sequence, -1);
  const initial = check(0, 1);
  assert.equal((await append(initial, -1)).stored, true);
  assert.equal((await loadWitnessRegister(path, citadelId, witnessId)).sequence, 0);
  await rejects(append(initial, 0), "WITNESS_SEQUENCE_GAP_OR_REPLAY");
  await rejects(append(check(2, 2), 0), "WITNESS_SEQUENCE_GAP_OR_REPLAY");
  await rejects(append(check(1, 0), 0), "WITNESS_REVISION_ROLLBACK");
  await rejects(append(check(1, 1, "b".repeat(64)), 0), "WITNESS_SAME_REVISION_CONFLICT");
  await rejects(append(check(1, 2), 0, wrong.publicKey), "WITNESS_SIGNATURE_DENIED");
  await rejects(append({ ...check(1, 2), sequence: 4 }, 0), "WITNESS_SIGNATURE_DENIED");
  const next = check(1, 2);
  const race = await Promise.allSettled([append(next, 0), append(next, 0)]);
  assert.equal(race.filter((r) => r.status === "fulfilled").length, 1);
  assert.equal(race.filter((r) => r.status === "rejected").length, 1);
  assert.equal((await loadWitnessRegister(path, citadelId, witnessId)).sequence, 1);
  await rejects(append(check(2, 3), 0), "WITNESS_STALE_SEQUENCE");
  const saved = await readFile(path, "utf8");
  await writeFile(path, "broken", "utf8");
  await rejects(append(check(2, 3), 1), "WITNESS_REGISTER_CORRUPT");
  await writeFile(path, saved, "utf8");
  assert.equal((await append(check(2, 3), 1)).sequence, 2);
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA witness register tests PASS");
