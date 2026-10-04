# ADR-0003: Cross-Surface Semantic Consistency via VORM9EVING

- **Status:** Accepted  
- **Date:** 2026-10-02  
- **Owner:** PALACO Foundation  
- **Deciders:** UX / Architecture / Governance

## Context
RIO surfaces (mobile, web, ELIXER) require UI flexibility.  
However, differing interface behavior must not change constitutional meaning, authorization semantics, or user understanding of state.

## Decision
PALACO enforces **semantic consistency across surfaces**:
- same conversation identity
- same state semantics
- same action boundary semantics
- same policy outcome meaning

UI presentation may vary (layout/interaction density/style), but meaning must remain invariant.

## Consequences
### Positive
- Predictable user mental model across devices
- Reduced governance ambiguity
- Consistent compliance and support behavior
- Better accessibility and trust

### Trade-offs
- Stricter UX contract for product teams
- Extra conformance testing across clients
- Requires shared terminology/state labels

## Alternatives Considered
1. **Surface-specific semantics**  
   Rejected: introduces ambiguity and governance risk.
2. **Partial semantic alignment**  
   Rejected: still permits critical divergence.
3. **Full semantic invariance with UI flexibility**  
   Accepted.

## Compliance Impact
Supports:
- RIO-SURFACE-COMPLIANT
- RIO-CONSTITUTIONAL-LANGUAGE-COMPLIANT
- Cross-surface UX integrity checks

## Links
- `docs/standards/rio/platform/RIO-UX-CROSS-SURFACE-001.md`
- `docs/standards/rio/glossary/RIO-GLOSSARY-001.md`
- `docs/standards/rio/platform/RIO-PLATFORM-001.md`
