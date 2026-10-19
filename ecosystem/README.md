# Document exchange candidate

`document-exchange.mjs` is the same bounded, dependency-free codec in the five
PALACO participants. The coordinator in Maurits-pixe/PALACO verifies every copy
and pinned participant revision, and exercises III6V9-Architect/local-qa's actual
module. `participant.mjs` exports only this repository's user-supplied documents
and reads the common packet. Sources are references, never source verification.

Packets are canonical UTF-8 JSON, at most 16 KiB, with a content SHA-256, fixed
source revision and a closed SYNTHETIC_ONLY boundary. Unknown/duplicate fields,
bad encodings, traversal, unsupported sources, corrupted content and authority
promotion are rejected. Imported status/origin remain USER metadata, unverified.
The module performs no network access or database mutation and carries no cookie,
provider identity, account selector, CSRF token, authorization or signing key.
Each application retains its own account and authorization checks.

This is a candidate document connection, separate from release authorization.
Existing release-registry contracts/gates and visual surfaces stay in force.
No shared login, merge, deployment, release or contact activation is included.

Run `node --test ecosystem/*.test.mjs`. The core coordinator additionally runs
the pinned cross-repository matrix and produces the CMV browser fixture. Its
real TLS/provider/storage tests verify the packet's authenticated round trip,
account isolation and conditional erasure on primary and restored storage.

The coordinated candidates are:

| Repository | Candidate role | Review |
| --- | --- | --- |
| Maurits-pixe/PALACO | Pinned workspace, CMV client and authenticated storage proof | This branch, stacked on verified-delete PR #81 |
| Maurits-pixe/palaco-genesis | Repository-bound document exporter/reader | [PR #132](https://github.com/Maurits-pixe/palaco-genesis/pull/132) |
| Maurits-pixe/PALACO-BOOK-1 | Pure CONCEPT/UNKNOWN knowledge-draft mapping | [PR #10](https://github.com/Maurits-pixe/PALACO-BOOK-1/pull/10) |
| Maurits-pixe/PALACO-INDUSTRIE | Public catalog for both owners and document participant | [PR #35](https://github.com/Maurits-pixe/PALACO-INDUSTRIE/pull/35) |
| Maurits-pixe/PALACO-Citadel | Grounded quotes using the pinned Q&A module | [PR #48](https://github.com/Maurits-pixe/PALACO-Citadel/pull/48) |
| III6V9-Architect/local-qa | Actual unchanged upstream, read-only at the locked commit | No upstream mutation |

`workspace.lock.json` fixes the participant revisions and source Git blobs.
`verify-workspace.mjs --workspace=/path/to/parent` verifies the six checkouts,
all 30 source/reader pairs, six actual upstream Q&A comparisons and six Book
drafts. The parent contains the folder names recorded in the lock file; the CI
workflow reproduces those checkouts. `--prepare` is a developer-only fixture
regeneration mode and prints PREPARED, never a completed verification result.

The retained fixture contains only the first twelve README lines from each
fixed public source revision. The required CMV browser phase uploads, downloads,
checks both hashes and conditionally erases every packet through the existing
session and CSRF boundary, on both primary and restored TLS storage. The client
is served only by the opt-in storage router; it grants no independent access.

This slice supplies tested data adapters and a reproducible authenticated flow.
It does not mount new Book/Q&A application routes or unify production identities.

The next candidate adds `/storage` exclusively to the existing opt-in CMV router.
It opens canonical packet files after an explicit local selection, checks the
content, saves with an explicit retention choice, lists the current account's
complete verified catalog, opens a pinned document and conditionally erases it.
The default account/Studio surface stays unchanged. The page reuses the existing
session/CSRF, exact-origin, CSP and no-store boundaries; it opens no production
account or contact access.

`storage-vault.mjs` validates lifecycle times, unique IDs, quotas and complete byte
totals, pins upload acknowledgements to the local bytes and verifies downloads
against the catalog and inner document. It uses fixed same-origin paths, bounded
JSON streams and an eight-second deadline, with no automatic mutation retries.
An uncertain upload retains only its ID/digest/retention/account metadata in
memory. Reconnecting to the same account and resubmitting identical bytes/retention
uses the same PUT ID. Logout, page hiding/navigation and account replacement clear
local data; old requests and file reads cannot repopulate a later session.
Recovery metadata is deliberately not durable: after leaving, hiding or reloading,
review the catalog before manually submitting another file. No localStorage,
IndexedDB, service worker or browser bearer token is used.

The document preview expires using server observation plus elapsed monotonic time,
independently of changes to the local wall clock. Catalog updates require a fresh
server read. The existing mandatory TLS browser phase now also exercises the page
with real provider login, reload, another account, checked erasure and logout on
primary and restored databases, including 390/1280px layout and touch controls.
