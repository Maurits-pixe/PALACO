import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import { createChallengeAnchor, verifyChallengeAnchor,
  challengeSnapshotDigest } from "./challenge-anchor.mjs";

const keys = generateKeyPairSync("ed25519");
const other = generateKeyPairSync("ed25519");
const hash = (n) => String(n).repeat(64);
const snapshot = { revision: 2, consumed: [hash("a"), hash("b")] };
const anchor = createChallengeAnchor({ anchorId: "A1", issuer: "TEST_ISSUER",
  citadelId: "LA", snapshot, issuedAt: 100, expiresAt: 150 }, keys.privateKey);
const context = { anchor, snapshot, citadelId: "LA", pinnedIssuer: "TEST_ISSUER",
  publicKey: keys.publicKey, observedAt: 120, trustedRevisionFloor: 2 };
const expect = (override, reason) =>
  assert.equal(verifyChallengeAnchor({ ...context, ...override }).reason, reason);
assert.equal(challengeSnapshotDigest(snapshot).length, 64);
const match = verifyChallengeAnchor(context);
assert.equal(match.matched, true);
assert.equal(match.safeToProceed, false);
assert.equal(match.authorityGranted, false);
assert.equal(match.independentWitnessVerified, false);
expect({ publicKey: other.publicKey }, "ANCHOR_SIGNATURE_DENIED");
expect({ anchor: { ...anchor, snapshotDigest: hash("c") } }, "ANCHOR_SIGNATURE_DENIED");
expect({ citadelId: "OTHER" }, "ANCHOR_CONTEXT_DENIED");
expect({ pinnedIssuer: "OTHER" }, "ANCHOR_CONTEXT_DENIED");
expect({ observedAt: 150 }, "ANCHOR_CONTEXT_DENIED");
expect({ observedAt: 99 }, "ANCHOR_CONTEXT_DENIED");
expect({ trustedRevisionFloor: 3 }, "ANCHOR_REVISION_FLOOR_VIOLATED");
expect({ snapshot: { revision: 1, consumed: [hash("a")] }, trustedRevisionFloor: 0 },
  "ANCHOR_LOCAL_ROLLBACK_SUSPECTED");
expect({ snapshot: { revision: 3, consumed: [hash("a"), hash("b"), hash("c")] } },
  "ANCHOR_STALE_SNAPSHOT");
expect({ snapshot: { revision: 2, consumed: [hash("b"), hash("a")] } },
  "ANCHOR_DIGEST_MISMATCH");
expect({ snapshot: { revision: 2, consumed: [hash("a"), hash("a")] } },
  "ANCHOR_CONTEXT_DENIED");
expect({ trustedRevisionFloor: undefined }, "ANCHOR_CONTEXT_DENIED");
assert.throws(() => challengeSnapshotDigest({ revision: 1, consumed: [] }),
  /CHALLENGE_ANCHOR_SNAPSHOT_INVALID/);
assert.throws(() => createChallengeAnchor({ anchorId: "A1", issuer: "I",
  citadelId: "LA", snapshot, issuedAt: 100, expiresAt: 4000 }, keys.privateKey),
  /CHALLENGE_ANCHOR_INPUT_INVALID/);
console.log("challenge-anchor: PASS (test-only cryptographic evidence; HOLD)");
