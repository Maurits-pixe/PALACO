import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { mkdtemp, rm, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadNonceStore, commitNonce } from "./nonce-store.mjs";
import { createNonceAnchor } from "./signed-nonce-anchor.mjs";
import { createWitnessCheckpoint, inspectWitnessedAnchor } from "./anchor-witness.mjs";

const anchorKeys = generateKeyPairSync("ed25519");
const witnessKeys = generateKeyPairSync("ed25519");
const wrongKeys = generateKeyPairSync("ed25519");
const dir = await mkdtemp(join(tmpdir(), "hara-witness-"));
const path = join(dir, "reception-nonces.json");
const anchorAt = async (id) => createNonceAnchor("LA-001",
  await loadNonceStore(path, "LA-001"),
  { anchorId: id, issuedAt: 1000, expiresAt: 1100 }, anchorKeys.privateKey);
const witnessFor = (a, sequence) => createWitnessCheckpoint(a,
  { witnessId: "external_witness", sequence, issuedAt: 1000, expiresAt: 1100 },
  witnessKeys.privateKey);
const inspect = (anchor, witness, changes = {}) => inspectWitnessedAnchor({
  path, citadelId: "LA-001", anchor, anchorPublicKey: anchorKeys.publicKey,
  witness, witnessPublicKey: witnessKeys.publicKey,
  pinnedWitnessId: "external_witness", minimumWitnessSequence: 2, now: 1050,
  ...changes
});
try {
  await commitNonce(path, "LA-001", "LA-001:sender:one", 0);
  const oldFile = await readFile(path, "utf8");
  const oldAnchor = await anchorAt("anchor_old");
  const oldWitness = witnessFor(oldAnchor, 1);
  await commitNonce(path, "LA-001", "LA-001:sender:two", 1);
  const latest = await anchorAt("anchor_new");
  const currentWitness = witnessFor(latest, 2);
  const accepted = await inspect(latest, currentWitness);
  assert.equal(accepted.witnessed, true);
  assert.equal(accepted.safeToProceed, false);
  assert.equal(accepted.antiRollbackEstablished, false);
  assert.equal((await inspect(oldAnchor, oldWitness)).reason, "WITNESS_CONTEXT_DENIED");
  assert.equal((await inspect(oldAnchor, currentWitness)).reason, "WITNESS_ANCHOR_MISMATCH");
  assert.equal((await inspect(latest, currentWitness,
    { witnessPublicKey: wrongKeys.publicKey })).reason, "WITNESS_SIGNATURE_DENIED");
  assert.equal((await inspect(latest, { ...currentWitness, minimumRevision: 1 })).reason,
    "WITNESS_SIGNATURE_DENIED");
  assert.equal((await inspect(latest, currentWitness,
    { pinnedWitnessId: "other" })).reason, "WITNESS_CONTEXT_DENIED");
  assert.equal((await inspect(latest, currentWitness,
    { now: 1100 })).reason, "WITNESS_CONTEXT_DENIED");
  await writeFile(path, oldFile, "utf8");
  assert.equal((await inspect(latest, currentWitness)).reason, "WITNESS_STORE_OR_ANCHOR_HOLD");
  assert.equal((await inspect(oldAnchor, oldWitness,
    { minimumWitnessSequence: 1 })).witnessed, true);
  // A compromised source for the "latest" sequence remains a critical gap.
} finally { await rm(dir, { recursive: true, force: true }); }
console.log("HARA anchor witness tests PASS");
