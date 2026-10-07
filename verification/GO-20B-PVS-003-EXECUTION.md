# GO-20B — PVS-003 execution evidence

Status: ORIGINAL CANDIDATE FAILED; MINIMALLY CORRECTED CANDIDATE PASSED LOCALLY.
Repository: Maurits-pixe/PALACO
Working branch: go-18/write-authorization-proof
Date: 2026-10-07 UTC

## Actual results

| Execution | Candidate commit | UTC start | Exit | Result |
| --- | --- | --- | --- | --- |
| Original, unchanged GO-20 candidate | `960a51b19059eb76a59a6c8caf1aa13831b062bf` | 11:07:57.249631 | 1 | FAIL |
| Minimal baseline-identity correction | `a1c977c9f3e2cd380cea1dabc50446812c8ac8c2` | 11:09:35.652938 | 0 | PASS |

The supplied identifier `96864384022191e7e6f6fd59134defbd3ae41151` is a Git
**commit**, not a tree. Its tree is
`da01553abfc4d07865b76cb99a13addd2477d4d3`. Both were verified from real Git
objects and GitHub. The original specification and verifier confused these
object types. No new baseline was selected.

## Original failure, retained verbatim

```text
PVS-003: FAIL
- frozen main tree mismatch: expected 96864384022191e7e6f6fd59134defbd3ae41151, got da01553abfc4d07865b76cb99a13addd2477d4d3
```

Exit code: 1. Stderr: empty. Raw stdout: 141 bytes, SHA-256
`a7d17f3724e99ac6a3a3af73efe03d0fb9c12736f8016cd45336796978bfa288`.
Original verifier blob: `8ffa9ef90eb7e925ea20b56f3d7f7d884a8fd38c`.
Original candidate tree: `182978e1f3a7c4163457b7edd93ca335911a7dcd`.

## Minimal candidate correction

Only `tools/pvs003_repository_provenance.py` and
`docs/verification/PVS-003.md` change verification behavior or its specification.
The verifier pins the original commit and its verified tree separately and
checks both using `git rev-parse --verify`. Missing or unreadable refs still
fail closed. Protected paths, classification, workspace and identifier checks
remain as in the original candidate.

Corrected verifier blob: `e332b0f2be87afa82dcfabf5dfdd2a248af5d0b4`.
Corrected candidate tree: `b72b68a09e6af0c50ebf8ebfb08f9c93489eac73`.

```text
PVS-003: PASS
Frozen repository baseline, protected historical material, classification boundary, workspace membership, and exact canonical identifier are preserved.
PVS-003 PASS != merge authority != canonical ascension
```

Exit code: 0. Stderr: empty. Raw stdout: 224 bytes, SHA-256
`9e3b3bcf61d83b67b9aeab64da31c4f7e98ebc8b9876697520f7ba93a3711795`.

## Runtime and execution envelope

The command actually executed was the bundled Python interpreter followed by
`tools/pvs003_repository_provenance.py`, with the candidate checkout as its
working directory. The exact executable and working directory are in each
execution JSON record. Runtime: Python 3.12.14, Git 2.53.0.windows.3,
Windows 11 build 26200. Each record contains UTC timestamps, exit code,
candidate commit/tree, local main commit/tree before and after, Git blob IDs,
SHA-256 hashes and lengths of all eight verifier inputs, and output hashes.

This was a **local non-cone sparse checkout**, with a complete Git object
database. Historical path names containing colons/newlines or a trailing-space
directory component cannot be fully checked out on this Windows host; WSL
was unavailable. Those original paths and blobs remain untouched in Git.
The sparse patterns are recorded in the execution JSON. Every file read or
tested for existence by the verifier was materialized from the real candidate.

Initial setup encountered network sandbox restrictions, Git ownership checks
between the sandbox and clone owner, and Windows newline conversion. These
were setup failures before the verifier ran, not PVS-003 verdicts. Execution
used the clone-owning account. Local `core.autocrlf=false` and
`core.protectNTFS=false` permit exact inputs and indexing the preserved names
without checking out the incompatible paths. Required inputs were restored
directly from Git blobs, and the index was refreshed. Each input's raw bytes
matched its committed blob before execution. Both measured runs began and
ended with clean Git status. The verifier itself was never mocked in these
two runs.

All five protected historical input blobs also match the frozen baseline.
The classification record and Cargo.toml are unchanged. Local main remained
at the frozen commit/tree throughout. GitHub read-back at 11:10:15 UTC also
confirmed that main and the pre-publication work-branch head were unchanged.

## Evidence files

- [Original execution metadata](GO-20B/original/execution.json)
- [Original raw stdout](GO-20B/original/stdout.txt)
- [Original raw stderr](GO-20B/original/stderr.txt)
- [Corrected execution metadata](GO-20B/corrected/execution.json)
- [Corrected raw stdout](GO-20B/corrected/stdout.txt)
- [Corrected raw stderr](GO-20B/corrected/stderr.txt)

Raw output files retain their Windows CRLF bytes; do not normalize them.
Evidence additions and the inactive CI draft follow the measured corrected
commit and do not change any verifier input. The evidence publication commit
is not itself claimed to be the commit measured in the table above.

### Local test commit versus GitHub publication

The corrected execution measured the **local** commit `a1c977c9f3e2cd380cea1dabc50446812c8ac8c2`.
Native Git push could not authenticate (interactive credential prompts were
disabled), so publication uses the connected GitHub app. GitHub creates a
new publication commit; its identity must not be substituted for the local
measured commit. The [raw local commit object](GO-20B/local-tested-commit.txt)
preserves the measured commit's tree, parent, author, timestamp and message.
Its Git commit-object SHA-1 is `a1c977c9f3e2cd380cea1dabc50446812c8ac8c2`.
Publication is checked for exact tree/blob equality, and only the authorized
work-branch ref is advanced without force. A local incremental Git bundle is
also included in the delivered evidence package so the measured commits can
be reconstructed on top of the original candidate.

## Focused validation of the correction

Independent review found the correction limited to the baseline identity
comparison and its specification. Five synthetic cases passed: the pinned
commit/tree pair passes; a changed commit with the same tree fails; a changed
tree fails; a missing main ref fails; and unavailable Git fails. These tests
mock Git responses and are explicitly separate from the two actual runs above.
Their [results](GO-20B/synthetic-validation.json) and
[test output](GO-20B/synthetic-validation.txt) are retained.

The CI draft's embedded Python compiled successfully. YAML/actionlint tooling
was unavailable locally, so no YAML/actionlint or workflow-execution pass is
claimed. CI activation and execution remain future work.

## CI candidate and limits

The [CI integration candidate](../docs/verification/ci/go-20b-pvs-003.yml.candidate)
is reviewable text outside `.github/workflows/`. It was prepared after the
successful local execution. Its [notes](../docs/verification/ci/GO-20B-CI-CANDIDATE.md)
describe baseline checks, output capture and activation constraints. It has
not been activated or dispatched. No PVS-003 CI PASS is claimed.

The verifier checks existence of protected paths, classification marker
substrings, workspace member strings and the exact identifier substring.
It does not prove document truth, full provenance/lineage, crate completeness,
all GO-19B entry conditions, runtime authorization or a complete Linux checkout.
The separately captured blob hashes support preservation of the five named
inputs for these runs; the verifier's existence test alone would not.

No historical material was renamed, removed or rewritten. No consolidation,
main update, merge, force push or history rewrite is part of GO-20B.

**PVS-003 local candidate PASS != CI PASS != merge authority != canonical ascension.**
