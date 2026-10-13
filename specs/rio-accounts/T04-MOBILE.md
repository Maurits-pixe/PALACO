# T04 — Mobile synthetic account interaction

Status: ENGINEERING CANDIDATE / SYNTHETIC_ONLY. ACCOUNT-1, integration and production remain HOLD.

This continues the tested T03 store at commit `cfe28d55f07dfa2ee81206665a46c9b50b4a1d83`. It provides a local mobile account interface; no identity service, hosting resource, real enrollment or invitation is provisioned. The existing online Citadel device-code diagnostic remains separate.

## Same-origin account flow

The fixed HTTPS BFF serves the HTML, JavaScript and CSS from explicit routes. Styles and scripts use the same origin; private source/runtime paths are not served. Content security policy permits those resources and rejects inline or third-party scripts. The RIO visual style uses code-native marks and system fonts.

The interface uses the existing Authorization Code + PKCE sign-in and reads only the session's own fictional account. Opaque cookies remain HttpOnly. CSRF is held only in page memory. There is no credential/login state in localStorage or sessionStorage, no provider-token display and no imported identity, role or authority.

Own-session checks close protected controls when the server rejects or cannot establish the session. Uncertain mutations require explicit retry and a fresh receipt. The separate local Studio note remains an unverified memory draft; it does not supply account state.

## Purpose-bound consent

GET /api/consent derives the actor only from the current server session. POST requires exact Origin, JSON content type, X-CSRF-Token and the strict object {scope, granted, revision}, under the existing256-byte limit. The sole scope is RIO_SYNTHETIC_SESSION_TEST_V1.

The envelope contains a receipt {scope, granted, revision, expiresAt} and fixed closed-account/authority flags. A granted receipt is a bounded synthetic test choice. It activates no personal account, contact room, Government seat, trusted reviewer or external execution.

The positive choice requires an explicit user action. Reading a receipt or importing a note never submits consent. Concurrent revisions produce one committed choice and a conflict; the client rereads the current receipt and requires a new explicit choice. Revocation is available through a native button and uses the same revision/CSRF boundary. Session expiry, actor revocation and database uncertainty close the protected API.

## Local Studio note

Import and download are explicit native controls for a small, strict JSON draft. Only local title/note text and a fixed unverified/false-authority envelope are accepted. Unknown keys, wrong schema/trust/authority fields, oversized content and credential/account-binding hints are rejected. The client renders text inertly and never applies an imported receipt or role.

The note lives in page memory. Import makes no server write; export serializes the current local draft and contains no cookie, CSRF, password, provider token or account authority. Clearing affects the draft only; reloading starts a new draft. Downloaded/imported files are source data, not approved accounts or consent.

## Mobile and accessibility evidence

The intended checks cover390-pixel Android Chromium emulation, a320-pixel narrow viewport, desktop keyboard interaction, visible focus, accessible names/landmarks, checkbox/button operation and live status semantics. The layout follows [W3C reflow guidance](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html); meaningful status updates follow [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).

Automated DOM/ARIA and keyboard checks are evidence for those tested paths. They do not claim actual Android hardware testing, a manual screen-reader run or full accessibility certification. Independent review remains open.

Final evidence must include the actual PostgreSQL-backed consent HTTP contract, mobile browser choices/conflicts/expiry/outage, actual downloaded JSON streams, hostile local imports that produce no grants or server writes, and the existing T02/T03 OIDC/restart/restore checks. Reports use fixed case IDs and source coordinates; credential values and private browser state are not published.
