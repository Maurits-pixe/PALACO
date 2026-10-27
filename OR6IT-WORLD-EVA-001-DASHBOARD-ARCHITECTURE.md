# OR6IT — WORLD-EVA-001 Dashboard Architecture

## Status and scope

**Recommendation:** conditional go for a read-only 2D dashboard design.

This is an architecture proposal, not an implementation plan approval. It
authorizes no merge, activation, publication, deployment, external effects, or
authority. A dashboard may show animation and reported state; neither is proof
of truth or authorization.

The initial dashboard should use the existing visual reference as a static
backdrop with accessible HTML, SVG, and (if needed) Canvas layers. Keep 3D
optional and out of the first slice; the 2D experience must remain complete.

## Independent clocks

Treat presentation, transport, and world history as separate concerns:

| Clock | Responsibility | Rule |
|---|---|---|
| Animation | Continuous visual motion, driven by `requestAnimationFrame` | Never restart or derive elapsed time from a data refresh |
| Data | Polling, SSE, or WebSocket updates | Update the read model only; never reset the animation clock |
| World | Event sequence, provenance, and trace | Apply events idempotently and preserve unknown/conflicting states |

Keep frame-by-frame values in the rendering layer, not UI framework state.
Data changes may trigger a short, bounded event indication, but must not reset
the animation origin or silently change the displayed authority state.

## Presentation layers

```text
Dashboard UI
├── Accessible HTML: status, regions, RIO event list, validation details
├── SVG: Horizon, Gate, Ring, Core, landmarks, routes, provenance paths
├── Canvas: optional particles, water, light, ambient effects
└── Static visual: WORLD-EVA-001 reference image
```

- Use HTML for readable, keyboard-accessible state and controls.
- Use SVG for named, individually styled geometric elements and paths.
- Use Canvas only for numerous decorative moving elements; it must not carry
  unique information unavailable elsewhere in the DOM.
- Keep the base image static. Do not treat visual detail as a technical
  specification or evidence of live state.

The repository currently has Vue-based previews, including
`modules/launcher-v1_2`; no EVA dashboard or React/Next.js application exists.
Choose a framework and exact placement during implementation review rather
than creating a parallel application by assumption.

## Read-only data boundary

The data layer may consume a versioned manifest and future read-only snapshot
or event endpoint. No EVA World API or World event stream is currently defined
by this package. Until one is separately specified and reviewed, use a local
synthetic fixture; do not imply that polling or a connected transport exists.

For an initial prototype, bounded polling can be considered after a read-only
endpoint exists. Prefer SSE for one-way server-to-dashboard updates; use
WebSocket only if an independently justified bidirectional requirement exists.
Transport delivery is not authorization. RIO's current transport draft
describes conversation delivery and cursors; it does not by itself define an
EVA World event contract.

Any future event consumer should:

- validate input against the reviewed manifest/event contract;
- retain sequence, event identity, provenance, validation state, and trace;
- deduplicate repeated delivery and detect sequence gaps or conflicts;
- show `UNKNOWN`, `INCOMPLETE`, `CONFLICT`, and `INVALID` without coercing
  them to success;
- expose `ACTIVE`, `APPROVED`, or `AUTHORIZED` only when separate reviewed
  records and gates support those states.

An event can update presentation data but cannot mutate World state, grant
authority, or cause an external effect.

## Motion and accessibility

Use elapsed time from a monotonic animation clock. Keep initial motion subtle:

- Ring rotation is slow and direction-stable.
- Core pulsing is gentle; brightness communicates visual activity only.
- Region animation is decorative and never a verification signal.
- Event reactions are brief and do not replace persistent status text.

Honor `prefers-reduced-motion` in JavaScript and CSS. In reduced-motion mode,
disable continuous rotation, parallax, and particle motion; retain static
state changes and readable event/status updates. Respect runtime preference
changes, not only the initial preference.

Pause decorative work when the document is hidden and resume without resetting
logical world time. Scale Canvas backing dimensions for device pixel ratio,
cap device work (especially on mobile), and provide a non-Canvas fallback.
Performance goals such as 60 FPS desktop and 30 FPS mobile are targets to
measure on named test devices, not guarantees.

## Proposed implementation sequence

1. Establish dashboard location, framework, and read-only data contract.
2. Build the static responsive dashboard and HTML status/read model.
3. Add SVG structure and verify keyboard, contrast, and reduced-motion behavior.
4. Add an independent animation loop and visibility handling.
5. Add optional, decorative Canvas effects only if profiling supports them.
6. Add a synthetic read-only data adapter and test malformed, stale, unknown,
   duplicate, gapped, and conflicting updates.
7. Define and review a real endpoint separately before connecting polling,
   SSE, or WebSocket.
8. Run browser, accessibility, and performance checks; retain human review.

## Acceptance conditions

- Data refresh never restarts continuous animation.
- Animation is presentation-only and cannot create authority.
- The complete dashboard remains usable with motion disabled and Canvas absent.
- Unknown, incomplete, invalid, and conflicting states remain visible.
- No writes, activation, publication, or external effects are possible.
- Tests use synthetic data and make no external network calls.

## Existing repository references

- `modules/launcher-v1_2/src/App.vue` and `modules/launcher-v1_2/src/style.css`
  show the existing Vue preview conventions and a reduced-motion rule.
- `website/styles.css` contains a site-wide reduced-motion rule.
- `docs/standards/rio/transport/RIO-TRANSPORT-001.md` is a draft transport
  standard for RIO conversations; it is not an EVA World event specification.

These references inform implementation alignment; they do not establish an
EVA runtime, API, or authorization contract.
