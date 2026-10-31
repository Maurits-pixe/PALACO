# GO-17 — Dependency Inventory & SBOM Provenance

**Status:** Implementation candidate  
**Repository:** `Maurits-pixe/PALACO`  
**Format:** SPDX 2.3 JSON  
**Parent gates:** GO-15 Workflow Supply-Chain Conformance, GO-16 Runtime Dependency & Container Provenance

## Objective

GO-17 turns the dependency identity controls established by GO-15 and GO-16
into a reproducible Software Bill of Materials.

The inventory is derived exclusively from committed evidence:

- root `Cargo.lock`;
- committed npm `package-lock.json` files;
- digest-pinned container references in GitHub Actions workflows.

## Governing rule

```text
locked dependency identity
+ immutable container digest
+ deterministic extraction
→ reproducible SPDX inventory
```

GO-17 does not infer missing license conclusions, suppliers, security status,
or constitutional authority. Where authoritative package licensing is not
established by the lockfile, SPDX uses `NOASSERTION`.

## CI artifact

The workflow generates:

`artifacts/go17/PALACO.spdx.json`

and uploads it as the `go-17-spdx-sbom` workflow artifact together with its
SHA-256 digest in the job log.

The generated file is intentionally not committed as a moving `main` artifact:
it is tied to the exact workflow commit through the SPDX document namespace and
GitHub Actions run provenance.

## Verification

GO-17 fails closed if:

- `Cargo.lock` is absent;
- a workflow container is not digest-pinned;
- the SPDX document lacks required document identity fields;
- package SPDX identifiers collide;
- `documentDescribes` and `DESCRIBES` relationships diverge;
- a container lacks its SHA-256 checksum;
- the generator invents license conclusions.

## Non-claims

An SBOM is an inventory, not a vulnerability certificate. GO-17 does not claim
that dependencies are secure, current, non-malicious, policy-approved, or
license-compatible. Vulnerability and policy evaluation require separate gates.
