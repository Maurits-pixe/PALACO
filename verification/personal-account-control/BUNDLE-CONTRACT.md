# Source review overlay v0.1 — unsigned, not a release

Object: personal-account reference slice v0.12 and its candidate RIO/CI changes.
The overlay requires a complete checkout at the recorded base HEAD. It is not a
standalone application, dependency mirror, container image, deployment or release.

From the repository root, generate fresh evidence and a new archive path:

```sh
python verification/personal-account-control/verify.py --output work/account-evidence-new-run
python verification/personal-account-control/bundle.py --evidence work/account-evidence-new-run --output work/account-review-new.zip
python verification/personal-account-control/bundle.py --check work/account-review-new.zip
```

The builder refuses an existing archive path and requires current passing source-
bound evidence. It binds the actual base HEAD and refuses tracked changes outside
the source allowlist; unrelated untracked scratch files are intentionally excluded.
All included source bytes must match their pre-copy/post-copy hash map. Evidence
is rechecked from the copied bytes, not only from its original file path.

## Contents and checks

manifest.json records the base HEAD, complete selected source SHA-256 map, archive
member hashes, REVIEW_CANDIDATE_NOT_RELEASE, production/account1 HOLD and explicit
rioServiceTests NOT_EXECUTED. source/ contains the selected source overlay, including
RIO Rust sources, embedded web assets, migrations/Cargo files, the workflow and
reference-slice docs/tests/inventory. evidence/ contains only evidence.json and its
exact digest. It excludes work/, .runtime/, databases, keys, environment files,
raw logs, generated session credentials, Git credentials and repository metadata.
Fixed synthetic constants in test source remain part of the reviewable code.

Archive member order, timestamps and file permissions are deterministic. The
inspector never extracts or executes members. It rejects traversal/absolute paths,
backslashes, directories, duplicate members, symlink members, excessive count or
uncompressed size, missing/extra members, mismatched hashes, stale current sources,
wrong base HEAD and nonpassing/inconsistent evidence. Current-source matching is
required: this is not a validator of arbitrary historical checkouts.

Hashes detect divergence; they do not authenticate authorship. Anyone able to
rewrite the unsigned manifest and report can recompute hashes. No reviewer
signature, historical completeness, trusted CI identity or release authority is
claimed. Tests and hashes do not turn missing runtime proof into PASS.

## Review/CI procedure

1. Preserve the archive, its external digest and the original evidence separately.
2. Use a complete repository checkout at manifest.baseHead. Review source/ and the
   manifest before applying any overlay; the checker performs no automatic apply.
3. Compare the source overlay with that base. Verify only the intended RIO metadata,
   reference slice and synthetic CI changes are present. Inspect unresolved gates
   in OIDC-BRIDGE-CONTRACT.md and CI-CONTRACT.md.
4. On an authorized candidate checkout, rerun the verifier and overlay checker.
   Actual remote publication/CI dispatch remains a separate authorized action.
5. Run the existing complete RIO Rust/OIDC/PostgreSQL/browser workflow. Retain its
   exact commit SHA, workflow/run/job IDs and results. Until then, full-service/CI
   verification remains blocked or NOT EXECUTED; no production transition follows.

Four new archive tests plus an actual build/check/tamper rehearsal verify this
packaging step. Prior evidence remains untouched and is not relabeled as current.

AI review: TRIAS — review artifact only, no authority or publication. ORACLE —
current local evidence and copied bytes are bound; registry/service/remote CI
remain unverified. MENTOR — this closes the local handoff artifact; obtain real
full-service results before extending the OIDC admission boundary.
