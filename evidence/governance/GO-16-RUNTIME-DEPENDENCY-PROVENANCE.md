# GO-16 — Runtime Dependency & Container Provenance

**Status:** Implementation candidate  
**Repository:** `Maurits-pixe/PALACO`  
**Scope:** CI/verification container images, Cargo dependency resolution, npm dependency lockfiles

## Objective

GO-16 extends GO-15 beyond GitHub Action references. The gate verifies the
runtime dependencies that CI actually executes.

The governing invariant is:

```text
container image → immutable sha256 digest
Cargo dependency resolution → committed lockfile + --locked
npm dependency project → committed package-lock.json
direct npm install → exact package version
```

## PostgreSQL CI image

A successful PALACO L.A. run pulled `postgres:17` and reported:

```text
Digest: sha256:31ba9c94a03ada9988f2bb493a22a75eef3a185884533e5cdbcd498ea835b08f
```

GO-16 therefore pins the already evidenced runtime as:

```text
postgres:17@sha256:31ba9c94a03ada9988f2bb493a22a75eef3a185884533e5cdbcd498ea835b08f
```

The affected CI services are:

- GO-06 Rust Workspace Tests
- GO-08 PVS-002
- GO-10 Foundation Audit
- PALACO L.A.

The existing RIO verification Compose fixture was already digest-pinned for
Keycloak and PostgreSQL and remains unchanged.

## Cargo resolution

Dependency-resolving Cargo commands in the Foundation/L.A. workflows now use
`--locked`. Formatting commands remain outside this rule because they do not
resolve dependencies.

The isolated RIO account service already uses its own committed
`services/rio-accounts/Cargo.lock` and locked Cargo commands.

## npm resolution

GO-16 verifies that npm projects with external dependencies have a colocated
`package-lock.json`.

Dependency-bearing projects currently covered:

- `modules/citadel-bastion-preview`
- `modules/launcher-v1_2`
- `modules/or6it-world-eva-001-preview`
- `verification/rio-accounts`

The Hannie candidate modules currently contain no external npm dependencies and
therefore do not require artificial lockfiles.

## Machine verification

Policy:

`evidence/governance/GO-16-RUNTIME-DEPENDENCY-POLICY.json`

Verifier:

`tools/verify_go16_runtime_dependency_provenance.py`

Feature-branch run:

- run `41025486917`
- result: **SUCCESS**

Observed machine output:

```text
GO-16 RUNTIME DEPENDENCY PROVENANCE: PASS
container_image_refs=6
container_images=SHA256_DIGEST_PINNED
cargo_dependency_commands=24
cargo_resolution=LOCKED
npm_dependency_projects=4
npm_dependency_projects=LOCKFILE_PRESENT
direct_npm_installs=1
direct_npm_install_versions=EXACT
postgres17_ci_image=postgres:17@sha256:31ba9c94a03ada9988f2bb493a22a75eef3a185884533e5cdbcd498ea835b08f
```

## Non-claims

Digest pinning and lockfiles establish reproducible identity boundaries. They do
not prove that a dependency is secure, correct, vulnerability-free, or
constitutionally authoritative.

GO-16 does not deploy, publish, spend, or grant runtime authority.
