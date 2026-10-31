# GO-19 — Container Vulnerability Remediation Status

**Repository:** `Maurits-pixe/PALACO`  
**Gate:** GO-19 — Container Image Vulnerability Evaluation  
**Status:** **BLOCKED / REMEDIATION ACTIVE / DO NOT MERGE AS PASS**  
**PR:** #99  
**Evidence subject before this record:** `3e3ca49ed98b99ba61fac0648aadc637c7995b1d`  
**Exception register:** empty

## Governing decision

GO-19 remains fail-closed.

A technically mergeable pull request, a lower vulnerability count, a newer image
tag, or a successful functional subset does not constitute security acceptance.

Closure requires zero unexcepted `CRITICAL`, `HIGH`, or `UNKNOWN` findings
for every in-scope exact image digest under the current policy, unless the owner
separately ratifies an exact, expiring exception with evidence.

No bulk exceptions, severity downgrade, silent ignore-unfixed rule, or blanket
risk acceptance is authorized.

## Current exact image evidence

### PostgreSQL 17 — current pin

`postgres:17@sha256:31ba9c94a03ada9988f2bb493a22a75eef3a185884533e5cdbcd498ea835b08f`

GO-19 evidence run: `41193559123`

- vulnerabilities: 378
- blocking: **93**
- CRITICAL: 2
- HIGH: 86
- UNKNOWN: 5
- MEDIUM: 144
- LOW: 141
- disposition: **BLOCK**

Remediation tracking: issue #100.

### PostgreSQL 18.6 Bookworm — current synthetic fixture pin

`postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c`

GO-19 evidence run: `41193559123`

- vulnerabilities: 479
- blocking: **107**
- CRITICAL: 4
- HIGH: 96
- UNKNOWN: 7
- MEDIUM: 199
- LOW: 173
- disposition: **BLOCK**

Remediation tracking: issue #101.

### Keycloak 26.8.1 — patch remediation candidate

`quay.io/keycloak/keycloak:26.8.1@sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b`

The previous 26.8.0 image had 120 findings and 12 blockers, including one
CRITICAL finding.

GO-19 evidence on 26.8.1:

- vulnerabilities: 105
- blocking: **5**
- CRITICAL: 0
- HIGH: 5
- MEDIUM: 67
- LOW: 33
- improvement: blockers **12 → 5** and CRITICAL **1 → 0**
- disposition: **BLOCK**

Remaining blockers:

1. CVE-2026-91403 — `java-21-openjdk-headless`
2. CVE-2026-91415 — `java-21-openjdk-headless`
3. CVE-2026-119373 — `sqlite-libs`
4. CVE-2026-119586 — `sqlite-libs`
5. CVE-2026-102554 — `com.google.guava:guava@33.6.0-jre`

Remediation tracking: issue #102.

## GO-19R PostgreSQL candidate evidence

Exploratory run: `41194135911`

These candidates were scanned as evidence only. They are **not** authorized
runtime migrations.

### PostgreSQL 17.11 Alpine

- Alpine 3.24:
  `postgres:17.11-alpine3.24@sha256:266d3c257594e195b309ae9d1805e54c788f1d7b375f56bf6c367aac6c917e7b`
- Alpine 3.23:
  `postgres:17.11-alpine3.23@sha256:05aa77262db9277fde6374bb2f901c9604b8a9373029e1a7993440c6aae48736`

Both scans:

- blocking: **27**
- CRITICAL: 1
- HIGH: 25
- UNKNOWN: 1
- MEDIUM: 31
- LOW: 3

This reduces observed blockers from 93 to 27 but remains **non-conformant**.

### PostgreSQL 18.6 Alpine

- Alpine 3.24:
  `postgres:18.6-alpine3.24@sha256:10a5c69a83035ab5239f5620d708520e8b28f5aa1f2b20143e6024532edadfb5`
- Alpine 3.23:
  `postgres:18.6-alpine3.23@sha256:1a0c23d53c1ad77468c8653fa6eed4f4105cfbef9e6f027bc1dfeb16949a8c29`

Both scans:

- blocking: **29**
- CRITICAL: 2
- HIGH: 26
- UNKNOWN: 1
- MEDIUM: 32
- LOW: 25

This reduces observed blockers from 107 to 29 but remains **non-conformant**.

## Keycloak 26.8.1 functional evidence

RIO synthetic run: `41194139643`

The run demonstrated successful operation through:

- fixture/source validation;
- Rust service build;
- disposable Keycloak + PostgreSQL startup;
- durable storage and revocation checks;
- protected consent HTTP boundary;
- bounded synthetic HTTPS BFF;
- real OIDC browser verification;
- database outage and explicit recovery;
- persisted sessions across restart;
- actor-scoped revocation;
- revocation survival after a second restart;
- bounded mobile login/draft-readiness probe.

The workflow nevertheless ended **FAIL**, in existing Android-emulated
`RIO-MOBILE-02` at `mobile-studio-setup`, waiting for own-account visibility
after callback.

Bounded failure observation:

- stage: `waiting-for-account`
- page kind: `bff-home`
- account visible: false
- login button visible: true
- document statuses: `[200,200]`
- own-account statuses: `[401]`
- own-account request-failed flag: true

The same run's dedicated Android `RIO-MOBILE-02` repetition passed **8/8**,
and the desktop-keyboard instance passed.

This symptom belongs to the existing intermittent investigation in issue #51.
**No causal attribution to Keycloak 26.8.1 is established. Root cause remains
UNKNOWN.** Functional acceptance of the patch therefore remains incomplete,
while the separate GO-19 security blockers independently remain decisive.

## Active blockers

| Track | Status | Evidence |
| --- | --- | --- |
| PostgreSQL 17 current image | BLOCKED | 93 blocking findings |
| PostgreSQL 18.6 current image | BLOCKED | 107 blocking findings |
| Keycloak 26.8.1 | BLOCKED | 5 HIGH findings |
| Keycloak functional acceptance | HOLD | full RIO run failed on existing issue #51 symptom |
| GO-19 exceptions | NONE | empty register |
| PR #99 | DRAFT / UNMERGED | merge forbidden while GO-19 is blocked |

## Required closure

GO-19 can close only when:

1. every detected runtime/verification container remains exact-digest pinned;
2. every such image is completely covered by GO-19 policy;
3. every exact image scan has zero unexcepted CRITICAL/HIGH/UNKNOWN findings;
4. any image migration passes its relevant functional regression suite;
5. RIO image changes pass the complete RIO synthetic verification, including
   backup/restore, without substituting an unrelated retry for evidence;
6. GO-10 and GO-13 through GO-18 remain green on the final candidate;
7. PR #99 is taken out of DRAFT only after the above evidence exists.

Until then:

```text
GO-19 = BLOCKED
PR-99 = DRAFT / UNMERGED
SECURITY EXCEPTIONS = NONE
CLAIM <= EVIDENCE
```
