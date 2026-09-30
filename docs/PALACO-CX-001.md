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

Local checks: 17 behavioral tests PASS; Studio and gateway smoke checks PASS. The workflow also runs the real consumer journey in pinned Playwright 1.62.1 Chromium and Firefox on GitHub runners. Screenshots, a Chromium A4 PDF, synthetic JSON round-trip fixtures and a machine-readable browser report are retained as head-bound CI artifacts for 14 days. Browser and visual results must be read from the exact pushed head before making a QA claim.

The browser suite exercises keyboard entry, complete ID fields, file-free dialog cancellation and Escape, image decoding and metadata edits, retained/restored revisions, reload, explicit RIO context, JSON round-trip and tamper rejection, storage-quota failure, all-section 390px/320px layouts and runtime/CSP/external-request boundaries. Chromium additionally checks the full multiline A4 print content and hidden editing/navigation controls. The test server uses local HTTP headers; these do not establish deployed-host security. Native operating-system print dialogs and physical devices remain outside automated coverage.

Titles, headings and paragraph fields grow to display their full content. The mobile/tablet inspector follows the normal page flow so metadata and revision history remain accessible without nested panel scrolling. Print builds plain-text mirrors of current field values, paginates paragraph lines, and excludes all navigation and editing controls. Browser QA identified and repaired native FormData capture after disabling fields, dialog cancellation validation, narrow-screen min-content overflow, cropped editable text and print fragmentation.

To run the browser suite where compatible browsers are installed:

```bash
PALACO_PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
PALACO_QA_OUTPUT=/absolute/path/to/qa-output \
node website/tests/studio-browser-test.mjs
```

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

## Browser/print evidence checkpoint

Product-source checkpoint: `517f3e7f379545aac179bf87c83fc2e78108e0f1`. Run [36724619901](https://github.com/Maurits-pixe/PALACO/actions/runs/36724619901): completed / success. 17 model/controller tests, two smoke suites and 23 real-browser checks PASS in Chromium 151.0.7922.34 and Firefox 153.0.

The artifact archive (ID `11101823876`) was downloaded and its SHA-256 matched `c83cba2d1f74cf0e670fb53ae797153a0086c80b4304fd4a28d9e63c9dc9ac96`. Desktop and mobile screenshots were inspected. All four A4 PDF pages were rendered and inspected; all 75 test-line labels were present as complete words, with navigation/editing controls excluded. This checkpoint records the reviewed evidence and does not automatically describe later heads. The final mobile-inspector/all-section test extension must pass its own head-bound CI run before handoff.

Gate status remains DRAFT / NOT MERGED / NOT DEPLOYED / UNVERIFIED. Automated UI and print checks are scoped implementation evidence, not canonical provenance or identity conformance.
