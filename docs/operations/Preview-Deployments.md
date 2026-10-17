# Web preview deployments

PALACO contains three independently deployable web apps. Each is configured as a separate Vercel project so every pull request gets its own preview URL without replacing another app's deployment:

| App | Vercel project root | Build output |
| --- | --- | --- |
| Public Gateway and Consumer Studio | `website` | `.` (static files; no build step) |
| Headquarters Launcher v1.2 | `modules/launcher-v1_2` | `dist` |
| Citadel Bastion preview candidate | `modules/citadel-bastion-preview` | `dist` |

## One-time Vercel setup

1. Install/authorize the Vercel GitHub integration for `Maurits-pixe/PALACO`.
2. Import the repository three times, creating one Vercel project for each app in the table. Set each project's **Root Directory** to the matching path and use its checked-in `vercel.json`.
3. Keep the production branch set to `main`. The project configs disable Git deployments directly from `main`; pull requests and other non-`main` branches continue to receive preview deployments. This setup does not replace a separately managed production deployment.
4. Ensure Preview Deployments are enabled in each project's Vercel Git settings.

## Finding and using a preview

### NEO first preview

For a NEO-only preview, import `Maurits-pixe/PALACO` as a single Vercel project with **Root Directory** `modules/launcher-v1_2`. There is no need to import the other apps yet. Use Node.js 22.x (at least 22.12) and the checked-in commands:

- Install: `npm ci`
- Build: `npm test && npm run build`
- Output: `dist`

Do not supply local certificates, API tokens or encryption keys: this is a static launcher build. Its controller regression tests must pass before the bundle is built; TLS and browser suites remain separate checks.

After authorizing the GitHub integration, keep `main` as the production branch and deploy the desired non-`main` branch to the **Preview** environment. The first repository import may attempt a production deployment; do not treat that as the requested preview. Confirm **Preview** in the deployment details and copy its actual HTTPS URL only after the deployment is **Ready**. No custom domain or production promotion is required. If review access should be restricted, configure Vercel Deployment Protection before sharing the URL.

Open the deployed launcher and check its browser console and security headers. Metadata checks still require reachable allowlisted module origins with CORS allowing this exact preview origin; a deployed launcher alone does not deploy AETHER or BASTION. Do not broaden the module allowlist or disable CORS to make a preview appear operational.

The account authorization and assigned URL are external deployment steps, not outcomes guaranteed by committing this configuration.

Vercel builds a new preview when a pull request is opened or updated. Its deployment URL is listed in the pull request's checks/deployment details and in the Vercel dashboard. Each app has a separate URL; use the URL for the app being reviewed. A later push creates a new deployment for that revision. These are preview deployments, not canonical production URLs.

The website runs without a build step. The launcher and Bastion use their existing `npm run build` scripts. Their local HTTPS certificate requirements apply only to local development/preview servers, not to Vercel's static build.

The launcher remains constrained to the module origins in `modules/launcher-v1_2/src/catalog.js`; deploying the launcher preview does not add its own Vercel URL to that allowlist or make the preview Bastion origin launchable.

## Local checks

```bash
node website/tests/smoke-test.mjs
node website/tests/studio-smoke-test.mjs
(cd modules/launcher-v1_2 && npm ci && npm test && npm run build)
(cd modules/citadel-bastion-preview && npm ci && npm test && npm run build)
```

The Rust crates are not web apps and do not receive preview URLs; their existing Rust build and test workflows remain unchanged.
