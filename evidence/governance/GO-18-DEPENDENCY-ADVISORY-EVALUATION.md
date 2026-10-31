# GO-18 — Dependency Vulnerability & Advisory Evaluation

**Status:** Implementation candidate  
**Repository:** `Maurits-pixe/PALACO`  
**Parent:** GO-17 SPDX SBOM Provenance  
**Advisory source:** GitHub Global Security Advisory Database

## Objective

GO-17 answers **what dependency identities are present**. GO-18 answers whether
those exact Rust and npm package versions currently match a GitHub-reviewed
security advisory or a GitHub malware advisory.

The policy is fail-closed:

```text
exact dependency identity
+ point-in-time advisory query
+ explicit exception register
→ PASS | BLOCK
```

## Source boundary

GO-18 uses GitHub's public global advisory endpoint and queries exact
`package@version` values for the Rust and npm ecosystems.

The evaluator records:

- subject commit;
- query timestamp;
- source/API version;
- packages evaluated;
- GHSA/CVE identity;
- advisory type and severity;
- affected package and exact installed version;
- vulnerable range and first patched version when supplied;
- policy status;
- exact exception usage.

Advisory data is time-varying. GO-18 evidence is therefore intentionally
**point-in-time evidence**, not a timeless proof.

## Decision policy

- reviewed advisory affecting an installed version → **BLOCK**;
- malware advisory affecting an installed version → **BLOCK**;
- advisory source unavailable/invalid → **BLOCK**;
- no matching advisories → **PASS**;
- exception → allowed only for exact GHSA + ecosystem + package + version,
  with rationale, approver, evidence and future expiry;
- expired, incomplete, unused or stale exception → **BLOCK**.

The initial exception register is empty. GO-18 does not create exceptions on
its own.

## Scope limits

GO-18 evaluates Rust and npm package versions represented by the GO-17 SBOM.

It does **not** claim:

- container-image vulnerability coverage;
- unreviewed GitHub advisories as blocking evidence;
- exploitability in the PALACO runtime;
- absence of unknown/zero-day vulnerabilities;
- dependency correctness, trustworthiness, or constitutional authority.

Container vulnerability evaluation remains a separate gate.

## Evidence artifact

The workflow uploads:

`artifacts/go18/PALACO-advisory-evaluation.json`

even when policy evaluation blocks, so a failure leaves inspectable evidence.
