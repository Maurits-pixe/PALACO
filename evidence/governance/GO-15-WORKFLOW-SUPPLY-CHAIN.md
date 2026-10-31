# GO-15 — Repository Workflow Supply-Chain Conformance

**Status:** Implementation candidate  
**Repository:** `Maurits-pixe/PALACO`  
**Scope:** all GitHub Actions workflows under `.github/workflows/`

## Objective

GO-15 separates repository-wide CI supply-chain governance from the historical
Foundation v1.0.0 audit.

The invariant is:

```text
external action → immutable commit SHA
workflow permissions → explicit
write permission → deny by default
write exception → explicit path + exact scopes
```

## Policy

Machine-readable policy:

`evidence/governance/GO-15-WORKFLOW-SUPPLY-CHAIN-POLICY.json`

Default:

- every external `uses:` reference must resolve to a 40-hex commit SHA;
- every workflow must define a top-level `permissions:` block;
- write permissions are forbidden unless explicitly registered.

Approved write exception:

| Workflow | Allowed write scopes | Purpose |
| --- | --- | --- |
| `.github/workflows/temporary-preview.yml` | `pages`, `id-token` | GitHub Pages deployment only |

No other workflow receives a write exception.

## Action pins introduced by GO-15

| Action | Immutable commit |
| --- | --- |
| `actions/checkout@v4` | `11d5960a326750d5838078e36cf38b85af677262` |
| `actions/checkout@v6` | `d23441a48e516b6c34aea4fa41551a30e30af803` |
| `actions/setup-node@v4` | `49933ea5288caeca8642d1e84afbd3f7d6820020` |
| `actions/setup-node@v6` | `249970729cb0ef3589644e2896645e5dc5ba9c38` |
| `actions/setup-python@v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/upload-artifact@v4` | `ea165f8d65b6e75b540449e92b4886f43607fa02` |
| `actions/configure-pages@v5` | `983d7736d9b0ae728b81ab479565c72886d7745b` |
| `actions/upload-pages-artifact@v3` | `56afc609e74202658d3ffba0e8f6dda462b719fa` |
| `actions/deploy-pages@v4` | `d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e` |
| `dtolnay/rust-toolchain` | `02cb101ec7c40f2c49e1d9714d64511d8e1b74de` |

## Initial remediation

GO-15 hardened these workflows without changing their functional intent:

- GO-044 Consumer Studio
- GO-6 Public Gateway
- Hannie agenda D-012
- Hannie B D-013
- PALACO L.A.
- Draft registry contract checks
- RIO accounts synthetic development
- Temporary public preview

## Verification

Feature-branch run:

- GO-15 run `41023807745`
- result: **SUCCESS**

The verifier scans the entire workflow directory and fails closed on:

- mutable external actions;
- missing explicit permissions;
- unapproved write permissions;
- stale or mismatched write exceptions.

## Non-claims

GO-15 does not authorize deployment, publication, spending, runtime authority,
or constitutional authority. An immutable action reference improves
reproducibility and supply-chain control; it does not prove the action itself is
correct or trustworthy.
