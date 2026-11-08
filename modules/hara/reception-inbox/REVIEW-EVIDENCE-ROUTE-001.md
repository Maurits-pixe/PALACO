# HARA-REVIEW-EVIDENCE-ROUTE-001 — human review dossier (DRAFT)

**Scope:** `Maurits-pixe/PALACO`, DRAFT PR #108, branch
`candidate/hara-reception-inbox-20261107`, directory
`modules/hara/reception-inbox/`.

**Candidate reference:** `39aeea386c4d2fd3b72dd21b9da20d6f4174cf62`
(last test-hardening commit observed when preparing this dossier; the dossier's
own commit will change HEAD). The reviewer MUST independently resolve the
current PR HEAD, base, changed-file list, workflow definition and CI run before
claiming review applies to current code. A later HEAD invalidates any unchecked
claim of current-head coverage.

**Gate:** `DRAFT / INTEGRATION HOLD / PRODUCTION HOLD / GO-13 HOLD`.
This document is a review worksheet, not approval or independent evidence.

## Reviewed path and expected invariants

1. `challenge-human-observation.mjs`: drafts scoped, bounded human observation
   metadata. Its reviewer label is unverified; a draft is not authentication.
2. `challenge-observation-proof.mjs`: creates a short-lived Ed25519 proof with
   test keys. Confirm canonical input binding, time boundaries and issuer pinning.
3. `challenge-observation-consume.mjs` and `challenge-register.mjs`: verify
   before one-time challenge commit; failed signatures must not mutate state;
   replay must be denied. Single-host semantics are NOT cross-host security.
4. `challenge-anchor.mjs`: verifies a signed digest of the ordered local register;
   a caller-supplied key is not independently trusted identity or custody.
5. `challenge-postcommit-inspection.mjs`: compare committed receipt, register,
   anchor and revision floor without repair. A matching observation still
   returns HOLD; read/inspect sequences are not atomic.
6. `challenge-incident-report.mjs`: emit allowlisted metadata and deterministic
   digest, without private reviewer values or claimed resolution.

## Evidence pointers (not copied evidence)

- `challenge-evidence-route.test.mjs`: end-to-end happy path with HOLD, wrong
  signature, replay, wrong commit digest, expiry, lock, wrong anchor public key,
  revision-floor mismatch, corrupt local register and private-value exclusion.
- Component tests: `challenge-observation-proof.test.mjs`,
  `challenge-observation-consume.test.mjs`, `challenge-anchor.test.mjs`,
  `challenge-postcommit-inspection.test.mjs`,
  `challenge-incident-report.test.mjs`.
- Prior local operator result: 27/27 `.test.mjs` suites reported PASS on the
  isolated scratch mirror. This result is local, not CI or independent audit.
- Current PR HEAD SHA, CI workflow/run/jobs, artifacts and independent
  reviewer identity: **UNVERIFIED for this dossier** until captured separately.

## Human reviewer checklist — record evidence, never auto-promote

For each item, record PASS/FAIL/UNKNOWN, reviewer identity and scope, timestamp,
exact HEAD SHA, link to independent evidence and notes. `UNKNOWN` is not PASS.

| ID | Required check | Initial status |
| --- | --- | --- |
| HR-01 | Confirm PR #108 HEAD/base and scope; no unrelated mutation | UNKNOWN |
| HR-02 | Verify signing fixture and pinning trust assumptions; reject rogue keys | UNKNOWN |
| HR-03 | Reproduce replay, concurrency and single-host failure boundaries | UNKNOWN |
| HR-04 | Evaluate rollback and independent anchor custody, including deletion | UNKNOWN |
| HR-05 | Inspect crash/lock handling; no automatic takeover or silent repair | UNKNOWN |
| HR-06 | Confirm no private values enter register/report/push payload | UNKNOWN |
| HR-07 | Verify deterministic report hash does not masquerade as authenticity | UNKNOWN |
| HR-08 | Validate CI evidence attached to this exact HEAD and workflow | UNKNOWN |
| HR-09 | Confirm PALACO ONE binding, revocation and real operator authority remain absent | UNKNOWN |
| HR-10 | Confirm Hannie agenda deny `STORAGE_EFFECT_DEADLINE_UNSUPPORTED` is intact | UNKNOWN |

## Blocking findings / release boundaries

- **B-01 TRUST:** No independent binding of test issuer/public key to a real
  PALACO ONE identity or revocation source.
- **B-02 CUSTODY:** Local anchor and revision floor do not establish independent,
  tamper-resistant custody; coherent rollback may go undetected.
- **B-03 RUNTIME:** Atomic multi-host persistence, verified clocks, push delivery,
  authorized ingestion, offline convergence and production durability remain
  unverified or unimplemented.
- **B-04 GOVERNANCE:** An AI-generated dossier, local green checks or a GitHub CI
  result cannot authorize integration, merge, production or recovery.

## AI review — three lenses, not three independent reviewers

- **TRIAS:** HOLD is required while trust, custody, production integration and
  authorization gates are unresolved. No new authority follows from this dossier.
- **ORACLE:** The test files offer reproducible local checks, but current-head
  CI artifacts, external custody and independent reviewer evidence are absent.
- **MENTOR:** Review the above ten items against a frozen PR HEAD and attach
  separate reviewer evidence; fix any FAIL in an explicitly tracked candidate.

**Transition:** DRAFT candidate → independently reviewed candidate is **NOT YET
AUTHORIZED** by this document; a competent human reviewer must record findings,
and the governing approval workflow must separately decide any later transition.

**No merge, signing, release, deployment, notification delivery, identity issuance,
Supabase mutation, challenge reissue, restoration or lock deletion is authorized.**
