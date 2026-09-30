# PALACO CX-001 — Consumer Experience v0.2

Status: DRAFT / LOCAL-FIRST / UNVERIFIED

## Purpose

CX-001 turns the PALACO public threshold into a first usable consumer workspace while preserving the GO-6 identity, proof and authority boundary.

The supplied L.A. reference board is translated into VORM9EVIN9 as a black perimeter, ivory work surface, restrained gold accents, editorial typography, large whitespace and literal provenance states.

The first template is deliberately sober: one clean sheet first.

## Consumer journey

1. Enter PALACO and choose Create ID / Build.
2. Create a browser-local PALACO ID with display name, alias and purpose.
3. Build with Heading, Text, Image, Provenance Card or Divider.
4. For every inserted image choose a visible role: Citadel image, Cover, Illustration, Source / evidence, or Watermark reference.
5. Save revisions locally.
6. Inspect creator, status, Citadel reference, revision and SHA-256 digest.
7. Ask RIO for local guidance.
8. Export a provenance-preserving .palaco.json document.

## Boundary

Canonical state in CX-001:

STATUS = LOCAL DRAFT
VERIFICATION = UNVERIFIED
AUTHORITY = NONE

A local PALACO ID is not a verified legal or real-world identity.
A SHA-256 digest is a change-detection primitive, not a trust decision.
An image role is metadata, not authenticity evidence.
A displayed Watermark reference is not a verified Watermerk.
RIO in this slice is deterministic guidance only; Live AI is not connected.

## VORM9EVIN9

- black perimeter / ivory canvas;
- restrained gold for lineage and emphasis;
- document remains visually dominant;
- tools recede into rail, toolbox and inspector;
- status language stays literal and visible;
- no badge, image, seal or mark may imply proof by appearance alone.

## Implemented tools

Identity: create, update, delete, local digest.
Documents: blank, Citadel note and Proof note templates.
Blocks: heading, text, image, provenance card, divider.
Image intent: Citadel image, Cover, Illustration, Source / evidence, Watermark reference.
Document metadata: purpose, Citadel reference, visibility, creator, status, verification, authority, revision, digest.
Library: save, open, delete, import validated JSON as a new local draft.
Output: JSON export of current content, with fresh document and export digests; browser Print / PDF.
RIO: deterministic local guide for ID, image use, revisions, import, provenance, save and export; explicit local document-summary attachment.

## Revision and import behavior

- Save retains previous snapshots and appends a sequential revision with a parent digest.
- Restoring earlier content prepares a draft. Saving appends a new revision; historical snapshots are retained.
- Original creator references are preserved when IDs change, are deleted or an export is imported. Each new saved revision records the current local editor separately.
- Document edits, image changes, reordering and visibility changes invalidate the visible saved-content state immediately.
- Saving is transactional with respect to browser storage: a quota or access failure leaves the saved revision unchanged and keeps working content open for export.
- Exports hash current working content, even when it has unsaved changes. Export does not mark the browser document as saved.
- Import checks schema, both present digests, document fields, status/authority boundaries, block identifiers, image MIME/data shape and browser image decoding. Unsupported or changed packages are rejected.
- An imported document receives a new document ID and an unverified source reference. The exported identity is not installed or treated as authenticated.
- PNG/JPEG/WebP only, 1.5 MB per newly inserted image, maximum dimensions 8192 × 8192, at most 100 blocks, and an 8 MB JSON import/export limit.
- Migration preserves the latest available v0.1 snapshot. Earlier revisions overwritten by v0.1 cannot be recovered.
- A change from another browser tab blocks further persistence until reload, allowing export of unsaved work first.

These are unsigned browser-local records. Users or other same-origin code can modify or delete browser storage. Digest matches are change-detection results, not authenticity or conformance evidence.

## Image and RIO experience

The existing “Use this image as…” selector can now be reopened to edit role, caption and source. Citadel/source/illustration images display their complete proportions; covers may crop. All roles remain UNVERIFIED.

RIO context is attached only through the explicit button. It includes title, block count, Citadel reference, revision and UNVERIFIED status; it is held in memory and never sent to a provider. Editing or switching documents clears the active context. Live RIO remains disconnected.

Visibility is labeled as intent. PRIVATE/SHARED/PUBLIC selections do not implement access control, share a document or publish it.

## Validation

Run from the repository root:

```bash
node --test website/tests/studio-model-test.mjs website/tests/studio-workspace-test.mjs
node website/tests/studio-smoke-test.mjs
node website/tests/smoke-test.mjs
```

Model and controller tests cover retained snapshots, restore-to-new-revision, current-content export, tampering, unsupported schemas/fields, unsafe image data, creator/editor separation, legacy migration, failed storage and cross-tab writes. The controller tests use a minimal DOM adapter and do not establish browser or visual conformance.

Local checks: 17 behavioral tests PASS; Studio and gateway smoke checks PASS. Full browser/visual/print QA remains pending because browser installation in this environment failed. GitHub CI status must be read from the exact pushed head before any CI claim.

The dedicated GO-044 workflow runs for pull requests targeting main or the GO-6 branch. The frozen GO-6 commit and PR #33 are not changed by this slice.

## Next gates

A separate review gate is required before any of the following may become live:

- account authentication and recovery;
- authoritative identity issuer integration;
- signed provenance receipts and key lifecycle;
- encrypted remote sync;
- live RIO provider connection with provider/model/prompt provenance;
- verified Citadel membership or role binding;
- Watermerk verification;
- public publication or authority grant.
