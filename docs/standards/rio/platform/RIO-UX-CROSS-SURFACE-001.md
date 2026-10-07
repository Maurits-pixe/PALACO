# RIO-UX-CROSS-SURFACE-001
## Cross-Surface UX & VORM9EVING Contract v0.1

### Status
Draft v0.1

### Last Updated
2026-10-06

## 1. UX goal
User experiences one coherent conversation across surfaces, regardless of frontend differences.

## 2. Semantic consistency rules
Across mobile/web/elixer clients, preserve:
- participant identity meaning
- message meaning and ordering
- action boundary meaning
- safety/consent signals
- provenance visibility (at least summary level)

## 3. Allowed variation
Surfaces may vary in:
- layout
- typography
- interaction density
- component style

Surfaces may not vary in:
- constitutional meaning
- authorization semantics
- policy outcome representation

## 4. Required interaction primitives
- conversation list
- timeline view
- participant/context panel
- message composer
- intent/action preview panel
- sync/reconnect status indicator

## 5. Human-readable state labels (recommended)
- “Connected”
- “Reconnecting…”
- “Queued (offline)”
- “Synchronized”
- “Action requires approval”
- “Not authorized”

## 6. Accessibility and clarity
- status changes must be perceivable without color-only signaling
- action vs message distinction must be explicit in copy and structure
- critical decisions require plain-language summaries

## 7. Acceptance criteria
- User starts on mobile and continues on web with same conversation identity.
- Offline/queued state is visible and understandable.
- Action requiring authorization is never presented as already executed.
