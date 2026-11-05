# OR6IT / WORLD-EVA-001 preview

This is a local, synthetic, read-only dashboard preview. It consumes the checked-in
EVA design fixture only. It has no World API, polling, SSE, WebSocket, backend,
persistent store, credentials, activation, or external effects.
The Vercel deployment applies a same-origin Content Security Policy, denies
framing and plugins, disables unneeded device permissions, and sets baseline
browser security headers through `vercel.json`. `public/_headers` carries the
same policy for static hosts that support that convention.

The manifest is checked against the current structural schema stub plus EVA
fixture-specific invariants. `STRUCTURALLY_VALID` describes document shape
only; constitutional validation and evidence remain `UNKNOWN` / `UNVALIDATED`.
The Ajv validator is generated as static ESM from the schema so browser-side
validation works without runtime code evaluation. After changing the schema,
run `npm run schema:generate`; tests and builds verify the generated validator.
The normalized fixture is also shown with a deterministic SHA-256 fingerprint.
That digest is an integrity aid only, not identity, provenance, or authority.
The image is served from the repository's canonical
`assets/world-eva-001-reference.png` path and is not technical evidence.

## Run locally

Requires Node.js 22.12 or newer.

```sh
npm ci
npm test
npm run build
npm run test:preview
npm run dev
```

`npm run test:preview` builds the production bundle, starts it on an ephemeral
localhost port, and checks the served security headers, app bundle, and image.

For the event/motion browser regression, install Chromium with
`npx playwright install chromium` and run `npm run test:browser`. It checks
that the synthetic event advances sequence 41 to 42 without replacing the
Canvas callback or restarting the existing SVG animation, including after
the event pulse ends. This is a local browser check, not a live-service test.
To use an existing Chrome/Chromium installation instead of downloading one,
set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable path.

The `EVA read-only preview` GitHub Actions workflow runs the unit contracts,
production HTTP smoke check, and Chromium event/motion regression on relevant
pull requests and pushes to `main` or `feat/or6it-world-eva-001-preview`.
The feature-branch push trigger also works when merge conflicts prevent PR
workflows from running. Changes to the shared schema or canonical
image also trigger it. This workflow tests only local synthetic data; it has
read-only repository permissions and does not deploy or authorize a World.

Open the localhost URL printed by Vite. The fixture-event button replays one
predefined synthetic event locally; it does not contact a service or mutate a
World. The scene's decorative animation has a pause/resume control, uses a
separate `requestAnimationFrame` loop, and pauses when the document is hidden
or reduced motion is requested by the operating system. Pausing preserves its
visual phase; resuming does not skip ahead or restart from the beginning.
