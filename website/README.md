# PALACO.NL · GO-6

Static first implementation of the PVD-001 v1.0 public gateway. It uses semantic HTML, one stylesheet and a small hash router so the site can be previewed without a build system.

## Run locally

```bash
python3 -m http.server 8080 --directory website
```

Open `http://localhost:8080/` and use the navigation. The canonical route model is documented in `docs/PVD-001/PALACO-NL-FULL-WEBSITE.md`; the hash form keeps direct navigation safe on static hosting.

## Evidence boundary

This release is a public content and navigation baseline. It does not issue identity, grant authority, establish provenance or connect to a live verification provider. Proof therefore returns `UNVERIFIED` when no authoritative provider is connected. No visible PALACO mark is treated as proof.

## Accessibility and performance

The shell includes semantic headings, keyboard-visible focus, a skip link, accessible form labels, status announcements, responsive layout, active-navigation state and reduced-motion support. It uses no external runtime dependency, video, tracking script or remote asset.

## Security boundary

The HTML carries a restrictive browser-enforced CSP and `no-referrer` policy. `website/security-headers.conf` defines the deployment contract for CSP framing restrictions, referrer policy, MIME-sniffing protection, browser capability restrictions and cross-origin opener isolation.

The repository file is **not deployment evidence**. Before publication, inspect the actual deployed HTTP response and verify that the hosting layer returns the required headers. Until that check succeeds, deployment-header status remains **UNVERIFIED**.

## Consumer Studio · CX-001

Open `/studio.html` from the local server. Start with a local ID and one blank sheet. Add document blocks or images, edit image roles/source notes, save retained revisions, restore earlier content into a new draft, or export/import `.palaco.json` copies. RIO offers deterministic local guidance and an explicit document-summary attachment.

All records remain LOCAL DRAFT / UNVERIFIED / AUTHORITY NONE. Storage is local to this browser and origin. Clearing browser data removes documents and revisions. Export to keep a portable copy; import creates a new draft and does not install an identity. Visibility describes intent and does not publish or secure a document.

See `docs/PALACO-CX-001.md` for behavior, validation commands, migration limits and browser/print coverage. The GO-044 workflow runs the consumer journey in Chromium and Firefox and retains screenshots, a Chromium A4 PDF and a JSON report for review. CI artifacts contain synthetic QA data. Titles, headings and paragraphs grow with their content; print uses complete text mirrors.
