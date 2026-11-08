import { createHash, sign, verify } from "node:crypto";

const id = (v) => typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
const digest = (v) => createHash("sha256").update(v).digest("hex");
const hex = (v) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v) => Number.isSafeInteger(v) && v >= 0;
const deny = (reason) => Object.freeze({ matched: false, reason, safeToProceed: false,
  authorityGranted: false, independentWitnessVerified: false });

function snapshotValid(snapshot) {
  return snapshot && integer(snapshot.revision) && snapshot.revision <= 100000 &&
    Array.isArray(snapshot.consumed) && snapshot.consumed.length === snapshot.revision &&
    snapshot.consumed.every(hex) && new Set(snapshot.consumed).size === snapshot.consumed.length;
}

// Canonical digest over *ordered* consumed hashes, rather than an unordered set.
export function challengeSnapshotDigest(snapshot) {
  if (!snapshotValid(snapshot)) throw new TypeError("CHALLENGE_ANCHOR_SNAPSHOT_INVALID");
  return digest(JSON.stringify({ revision: snapshot.revision, consumed: snapshot.consumed }));
}

function payload(value) {
  return JSON.stringify({ schema: value.schema, anchorId: value.anchorId,
    issuer: value.issuer, citadelId: value.citadelId, revision: value.revision,
    snapshotDigest: value.snapshotDigest, issuedAt: value.issuedAt,
    expiresAt: value.expiresAt });
}

// Test-only external anchoring fixture. Its signature does not assert independent custody.
export function createChallengeAnchor({ anchorId, issuer, citadelId, snapshot,
  issuedAt, expiresAt } = {}, privateKey) {
  if (!id(anchorId) || !id(issuer) || !id(citadelId) || !snapshotValid(snapshot) ||
      !integer(issuedAt) || !integer(expiresAt) || expiresAt <= issuedAt ||
      expiresAt - issuedAt > 3600) throw new TypeError("CHALLENGE_ANCHOR_INPUT_INVALID");
  const record = { schema: "HARA_CHALLENGE_ANCHOR_TEST_V1", anchorId,
    issuer, citadelId, revision: snapshot.revision,
    snapshotDigest: challengeSnapshotDigest(snapshot), issuedAt, expiresAt };
  return Object.freeze({ ...record,
    signature: sign(null, Buffer.from(payload(record)), privateKey).toString("base64url") });
}

// Floor must be supplied from separately retained evidence; local state cannot establish it.
export function verifyChallengeAnchor({ anchor, snapshot, citadelId, pinnedIssuer,
  publicKey, observedAt, trustedRevisionFloor } = {}) {
  if (!anchor || anchor.schema !== "HARA_CHALLENGE_ANCHOR_TEST_V1" ||
      !id(anchor.anchorId) || !id(anchor.issuer) || anchor.issuer !== pinnedIssuer ||
      !id(citadelId) || anchor.citadelId !== citadelId ||
      !integer(anchor.revision) || anchor.revision > 100000 ||
      !hex(anchor.snapshotDigest) || !integer(anchor.issuedAt) ||
      !integer(anchor.expiresAt) || anchor.expiresAt <= anchor.issuedAt ||
      anchor.expiresAt - anchor.issuedAt > 3600 || !integer(observedAt) ||
      observedAt < anchor.issuedAt || observedAt >= anchor.expiresAt ||
      !integer(trustedRevisionFloor) || !snapshotValid(snapshot) ||
      typeof anchor.signature !== "string" ||
      !/^[A-Za-z0-9_-]+$/.test(anchor.signature)) return deny("ANCHOR_CONTEXT_DENIED");
  let authentic = false;
  try { authentic = verify(null, Buffer.from(payload(anchor)), publicKey,
    Buffer.from(anchor.signature, "base64url")); } catch { authentic = false; }
  if (!authentic) return deny("ANCHOR_SIGNATURE_DENIED");
  if (anchor.revision < trustedRevisionFloor || snapshot.revision < trustedRevisionFloor)
    return deny("ANCHOR_REVISION_FLOOR_VIOLATED");
  if (snapshot.revision < anchor.revision) return deny("ANCHOR_LOCAL_ROLLBACK_SUSPECTED");
  if (snapshot.revision > anchor.revision) return deny("ANCHOR_STALE_SNAPSHOT");
  if (challengeSnapshotDigest(snapshot) !== anchor.snapshotDigest)
    return deny("ANCHOR_DIGEST_MISMATCH");
  return Object.freeze({ matched: true, reason: "ANCHOR_SNAPSHOT_MATCH",
    snapshotDigest: anchor.snapshotDigest, revision: anchor.revision,
    safeToProceed: false, authorityGranted: false, independentWitnessVerified: false });
}
