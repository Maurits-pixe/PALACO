# OR6IT / WORLD-EVA-001 preview

This is a local, synthetic, read-only dashboard preview. It consumes the checked-in
EVA design fixture only. It has no World API, polling, SSE, WebSocket, backend,
persistent store, credentials, activation, or external effects.

The manifest is checked against the current structural schema stub plus EVA
fixture-specific invariants. `STRUCTURALLY_VALID` describes document shape
only; constitutional validation and evidence remain `UNKNOWN` / `UNVALIDATED`.
The image is served from the repository's canonical
`assets/world-eva-001-reference.png` path and is not technical evidence.

## Run locally

Requires Node.js 22.12 or newer.

```sh
npm ci
npm test
npm run build
npm run dev
```

Open the localhost URL printed by Vite. The fixture-event button replays one
predefined synthetic event locally; it does not contact a service or mutate a
World. Animation uses a separate `requestAnimationFrame` loop and pauses when
the document is hidden or reduced motion is requested.
