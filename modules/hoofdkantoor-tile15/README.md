# PALACO Hoofdkantoor — PALACO Phone Testlab / tegel 15

**Status: source-only integration candidate; PRIVATE / BROWSER ACCEPTANCE HOLD / PRODUCTION HOLD.**

The existing private ChatGPT Site already has 14 cards, including **PALACO PHONE (#08)**.
This change proposes a **separate** #15 card. Do not replace or silently modify #08.

## Site destination

Existing private project: `appgprj_6ac53a9de6048191af2f6d0da56d2cea`.
Existing URL: https://palaco-hoofdkantoor-tijdelijk.mauritsvang1.chatgpt.site

**This GitHub change does not deploy or change that Site.** The Site editor / authorized Work process must integrate this catalog entry into its actual source, preserving all existing cards, saved addresses, favorites and language preferences. No public publication or access-mode changes.

## Card behavior

- ID: `palaco-phone-testlab`; ordering 15, after EARTH.
- Action A: `http://127.0.0.1:8765/` — the Python/SQLite local PP app **on the same physical device**. HTTPS launchers may block mixed-protocol navigation. No LAN binding, proxy, tunnel, embedded iframe or automatic data transfer.
- Action B: the source GitHub repository; internet needed.
- Action C: draft PR #2 with browser acceptance evidence and remaining blockers; internet needed.
- State is permanently explicit: `BROWSER_ACCEPTANCE_HOLD`, `production=HOLD` until reviewed evidence supports a separate decision.
- Use 12-language launcher translations, adaptive card layout (390px), focus-visible keyboard interaction, favorites, search and dynamic card counts. Treat `navigator.onLine` only as network hint — not as proof that the local app server is running.
- Do not create official identifiers or phone service. A P.P. identity choice is not a telephone number.

## Evidence / release gate

- Prior pre-browser CI: **PASS**, run 41408764447 (73 tests on its commit).
- Ephemeral Chromium browser CI: **FAIL**, run 41410806967; do not label browser acceptance PASS.
- Human acceptance **not recorded**; production and official issuance **HOLD**.

## Acceptance

The site must still have the existing 14 entries **unchanged**, plus exactly one #15 entry with stable ID. Verify keyboard, mobile, search, links, language switching, favorites, no access-control regression, and private-site access. Deploy only after authorized owner review.

A separate self-contained preview and Node 7-case contract test suite is delivered as `palaco-hoofdkantoor-pp-tegel-v2.zip` in the conversation. This repository folder intentionally stores only the data/contract rather than pretending to be the live ChatGPT Site source.
