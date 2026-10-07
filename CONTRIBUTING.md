# Contributing

Read [GOVERNANCE.md](GOVERNANCE.md), [ARCHITECTURE.md](ARCHITECTURE.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before proposing changes.
Use issues and pull requests in
[Maurits-pixe/PALACO](https://github.com/Maurits-pixe/PALACO).

## Development

The existing workspace uses Rust edition 2024 and declares Rust 1.90 as its
minimum. The foundation workflows currently select Rust 1.98.1. Install Rust
with the rustfmt and Clippy components and run commands from the repository
root. Do not create a second Genesis workspace.

```sh
cargo metadata --no-deps --format-version 1
cargo fmt --all -- --check
cargo check --workspace --all-targets
cargo build --workspace --all-targets
cargo test --workspace --all-targets
cargo clippy --workspace --all-targets -- -D warnings
python3 tools/pvs001_workspace_integrity.py
python3 tools/pvs002_cross_crate_contracts.py
python3 tools/go10_audit.py
```

These are existing repository checks, not guaranteed successes. Preserve
nonzero exits and their output in evidence. The full workspace also includes
the existing `palaco-la` extension; its database integration prerequisites
are distinct from the seven foundation crates.

## Required boundaries

- `#![forbid(unsafe_code)]` in Genesis crate entry points.
- Inherit workspace lints: `unwrap_used = "deny"` and `todo = "deny"`.
- No `Mutex` or `RwLock` in Genesis code.
- No new subsystems before Foundation/Core consolidation has evidence.
- Runtime and evolution may not grant themselves constitutional authority.
- Do not weaken tests or audits to obtain a PASS.

Keep changes small, readable and scoped to the active gate. Include source
references, exact commands, outputs, tool versions and outstanding blockers
in verification records. See [RELEASE.md](RELEASE.md) for certification rules.
Contributions remain under the existing `MIT OR Apache-2.0` license.
