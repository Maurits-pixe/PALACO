import assert from "node:assert/strict";
import { mkdtemp, open, unlink, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadNonceStore, commitNonce } from "./nonce-store.mjs";

const dir = await mkdtemp(join(tmpdir(), "hara-nonce-"));
const path = join(dir, "reception-nonces.json");
assert.equal((await loadNonceStore(path, "LA-001")).revision, 0);
assert.equal((await commitNonce(path, "LA-001", "LA-001:device_a:nonce_001", 0)).committed, true);
assert.equal((await loadNonceStore(path, "LA-001")).revision, 1);
await assert.rejects(commitNonce(path, "LA-001", "LA-001:device_a:nonce_001", 1), /NONCE_REPLAY_DENIED/);
await assert.rejects(commitNonce(path, "LA-001", "LA-001:device_a:nonce_002", 0), /NONCE_STALE_REVISION/);
await assert.rejects(commitNonce(path, "OTHER", "LA-001:device_a:nonce_002", 1), /NONCE_COMMIT_INPUT_INVALID/);
const lock = await open(path + ".lock", "wx");
try { await assert.rejects(commitNonce(path, "LA-001", "LA-001:device_a:nonce_002", 1), /NONCE_WRITER_LOCKED/); }
finally { await lock.close(); await unlink(path + ".lock"); }
const attempts = await Promise.allSettled([
  commitNonce(path, "LA-001", "LA-001:device_a:nonce_002", 1),
  commitNonce(path, "LA-001", "LA-001:device_a:nonce_002", 1)
]);
assert.equal(attempts.filter((r) => r.status === "fulfilled").length, 1);
assert.equal((await loadNonceStore(path, "LA-001")).revision, 2);
const raw = await readFile(path, "utf8");
await writeFile(path, raw.replace("nonce_001", "tampered"));
await assert.rejects(loadNonceStore(path, "LA-001"), /NONCE_STORE_INTEGRITY_FAILED/);
console.log("HARA durable nonce candidate tests PASS");
