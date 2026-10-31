# OR6IT / WORLD-EVA-001 — synthetic preview

This standalone Vue preview is a static interface study. All displayed values and sequence entries are local, invented fixtures; they are not observations, forecasts, or authoritative World state.

The UI is read-only. It has no API, network transport, polling, authentication, action controls, activation behavior, or external effects. The orbital illustration is 2D and decorative; its CSS animation is separate from the fixtures and is disabled for `prefers-reduced-motion`.

## Run locally

Use Node 22.12 or newer:

```bash
npm ci
npm test
npm run dev
```

Create a static bundle with `npm run build`; inspect it locally with `npm run preview`. No credentials, API endpoints, or external services are required.
