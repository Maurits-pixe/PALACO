# Public candidate publication plan v0.13 — NOT AUTHORIZED / NOT EXECUTED

Repository: Maurits-pixe/PALACO (public; observed through connected GitHub reads).
Observed main: b773ba7f8b02a11fc528f47d9481e92a28015e1d.
Local HEAD: 1b2065af0dfe82e25b3f62c80d9f9873563f6afd.
Remote main was 18 commits ahead with no divergence at observation time.
No local rebase, remote write, publication or CI dispatch was performed.

## Completed preparation

The only overlap between the previously prepared candidate and upstream's changed
paths was .github/workflows/rio-accounts-synthetic.yml. A three-way local merge
preserved the account verification step/path triggers and upstream's account
readback test plus isolated mobile database-outage browser stage.

The three associated prerequisite source files were copied byte-for-byte from the
pinned remote main (Git blob hashes verified locally):

- verification/rio-accounts/test_account_readback.mjs:
  0a24da4acd1cf3bb730049186b0997300af1342f
- verification/rio-accounts/mobile/helpers.mjs:
  23397d000febae3a22ac154db0a7af1801df1102
- verification/rio-accounts/mobile/interaction.spec.mjs:
  e4775b6733de75612ce4a9d465da1f65d60f95e6

These are upstream parity copies, not new behavioral changes relative to that
remote main. All are now source-bound by the local verifier. Other unrelated
upstream Docker/Aether/advisory changes must be retained from the remote parent,
not overwritten with the older local checkout. The local worktree remains based
on its original HEAD; this is not a claim of a complete main rebase or latest-main
runtime verification. Prior bundles and reports stay historical.

## Exact proposed external action

After explicit user authorization:

1. Recheck that remote main still equals the observed SHA. If it moved, reconcile
   affected paths again and make a fresh candidate/evidence record first.
2. Create a new branch codex/personal-account-control-v0-13 in Maurits-pixe/PALACO,
   parented from that current main, preserving the upstream tree.
3. Add the source-bound reference slice, the RIO lifecycle_bridge.rs module,
   the additive /api/me boundary and the combined synthetic CI workflow.
   Do not upload work/, databases, runtime secrets or generated credentials.
   Existing upstream-parity files need no separate change relative to main.
4. Open a draft PR targeting main with the prepared description. This publishes
   code in a public repository and may trigger ordinary pull-request CI.
5. Observe exact head/run/job results. Do not merge, enable auto-merge, deploy,
   activate accounts or turn a successful CI result into runtime authority.

A generic continuation GO has not been treated as permission for that public
publication. The applicable PALACO GO skill explicitly separates publication
permission from local construction and checks. This plan does not grant it.

## Prepared PR description

Title: Add synthetic personal-account lifecycle verification and explicit OIDC activation boundary

The candidate models invitation, staging, review, activation and suspension as
separate controlled transitions. It adds an explicit refusal boundary to the
synthetic RIO /api/me response: verified OIDC identity does not attest strong
authentication or confer personal-account activation authority.

The reference slice includes staged lifecycle/evidence checks, final session and
expiry revalidation, independent deny storage, per-start fencing, a disposable
integrated rehearsal and source-bound local evidence/overlay tooling. The existing
synthetic CI workflow runs these checks before its unchanged full Rust/OIDC/storage
stages, while preserving the current main's mobile/readback fixes.

Validation: 137 slice Python tests and 8 existing review-gate tests; standalone
Rust refusal module tested separately. Full Rust service build/router/OIDC checks
remain unexecuted locally because axum is unavailable and the crates registry
proxy is unreachable. The upstream Node readback test also cannot load locally
because Playwright is absent from the offline cache; syntax checks pass. Actual
remote CI results must be attached to this PR after execution.

Scope/status: synthetic local candidate only. No actual MFA or human authority
attestation, no lifecycle admission from OIDC, no deployed route, and no production
activation. ACCOUNT-1 and production HOLD; real service integration NOT VERIFIED.

## AI review using three lenses

TRIAS: local preparation authorized, public publication awaiting explicit scope
approval, production HOLD. ORACLE: remote main drift and blob parity are observed;
local Python tests are separate from blocked Rust/Playwright and absent remote CI.
MENTOR: publish only the reviewed candidate after permission, then collect actual
full-service CI evidence before proceeding toward runtime admission.
