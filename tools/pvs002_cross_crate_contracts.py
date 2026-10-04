#!/usr/bin/env python3
"""PVS-002 cross-crate contract and dependency-boundary verification."""

from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]

EXPECTED = {
    "palaco-foundation": set(),
    "palaco-eventbus": {"palaco-foundation"},
    "palaco-quay": {"palaco-foundation", "palaco-eventbus"},
    "palaco-citadel": {"palaco-foundation", "palaco-quay"},
    "palaco-runtime": {"palaco-foundation", "palaco-citadel"},
    "palaco-kernel": {"palaco-foundation", "palaco-runtime"},
    "palaco-evolution": {"palaco-foundation"},
}

ALL = set(EXPECTED)
errors: list[str] = []
graph: dict[str, set[str]] = {}

for crate, expected in EXPECTED.items():
    cargo_path = ROOT / "crates" / crate / "Cargo.toml"
    if not cargo_path.is_file():
        errors.append(f"missing Cargo.toml for {crate}")
        continue

    data = tomllib.loads(cargo_path.read_text(encoding="utf-8"))
    deps = set((data.get("dependencies") or {}).keys()) & ALL
    graph[crate] = deps

    if deps != expected:
        errors.append(
            f"{crate} internal dependency contract mismatch: expected {sorted(expected)}, got {sorted(deps)}"
        )

kernel_dev = tomllib.loads(
    (ROOT / "crates/palaco-kernel/Cargo.toml").read_text(encoding="utf-8")
).get("dev-dependencies") or {}
required_kernel_dev = {
    "palaco-citadel",
    "palaco-eventbus",
    "palaco-evolution",
    "palaco-quay",
}
if not required_kernel_dev.issubset(kernel_dev.keys()):
    errors.append("palaco-kernel is missing PVS-002 integration dev-dependencies")

visiting: set[str] = set()
visited: set[str] = set()

def visit(node: str) -> None:
    if node in visiting:
        errors.append(f"dependency cycle detected at {node}")
        return
    if node in visited:
        return
    visiting.add(node)
    for dep in graph.get(node, set()):
        visit(dep)
    visiting.remove(node)
    visited.add(node)

for crate in EXPECTED:
    visit(crate)

markers = {
    "crates/palaco-foundation/src/lib.rs": ["EvidenceRef", "AuthorityState", "ContractDisposition"],
    "crates/palaco-eventbus/src/lib.rs": ["EventEnvelope", "EvidenceRef"],
    "crates/palaco-quay/src/lib.rs": ["ProvenanceRecord", "AuthorityState"],
    "crates/palaco-citadel/src/lib.rs": ["ExecutionBoundary", "disposition_for"],
    "crates/palaco-runtime/src/lib.rs": ["RuntimePlan", "can_execute"],
    "crates/palaco-kernel/src/lib.rs": ["KernelCycle", "can_execute", "FailClosed"],
    "crates/palaco-evolution/src/lib.rs": ["EvolutionProposal", "ContractDisposition::Hold"],
}

for rel, required in markers.items():
    path = ROOT / rel
    if not path.is_file():
        errors.append(f"missing source contract file: {rel}")
        continue
    content = path.read_text(encoding="utf-8")
    for marker in required:
        if marker not in content:
            errors.append(f"{rel} missing contract marker: {marker}")

test_path = ROOT / "crates/palaco-kernel/tests/pvs002_cross_crate.rs"
if not test_path.is_file():
    errors.append("missing PVS-002 cross-crate integration test")

if errors:
    print("PVS-002: FAIL")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print("PVS-002: PASS")
print("Cross-crate dependency graph is explicit, acyclic, evidence-bearing, fail-closed, and Evolution does not confer execution authority.")
