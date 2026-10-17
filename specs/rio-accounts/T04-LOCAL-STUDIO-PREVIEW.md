# T04 — A readable local Studio work sheet

Status: ENGINEERING DRAFT / SYNTHETIC_ONLY / NO MERGE OR DEPLOY.

The Studio now separates a quiet editing area from a paper-like reading preview.
Wide screens show them side by side; mobile stacks them in reading order. Native
labels, field limits, focus styles and the existing save/open/clear actions remain.
The local and unverified boundaries are visible in the preview itself.

Title and note counters use JavaScript string length, matching the existing native
maxlength and import validator limits of 80 and 2000 UTF-16 units. Emoji and
combining marks retain that rule. After an accepted import, the counters and
preview read back native field values, including the browser's existing single
line/newline handling. No additional trimming or normalization is introduced.

Only fixed nodes' textContent receives draft text, so markup remains literal.
Whitespace is preserved visually and long words wrap. The bounded reading region
can be focused and scrolled with the keyboard so a long note does not push the
file actions far down the page. Empty fields have neutral
placeholders; the draft label says either empty or only in this page. It never
claims persistence, verification, account access or confirmed consent. New nodes
have no per-keystroke live announcements or focus movement. Editing, accepted
import, clearing and pagehide clearing update all local views; rejected or stale
imports cannot overwrite them. Existing export semantics and empty authority stay.

The separate Node browser presentation checks use actual web assets and a fixed
401 account stub. All other network targets are refused. They require the pinned
Chromium and explicitly prove presentation only, without credentials or a real
OIDC claim. They cover literal text, limits, input/import/clear behavior, privacy,
native labels, focus and narrow layout. They do not use the real-provider evidence
reporter. Short assertions also extend the existing real mobile Studio case,
retaining its canonical exports, zero writes, no persistent state and unchanged
account/consent receipt comparisons.

No account request, identity binding, authentication/consent decision, timer,
polling rule, cookie, lifetime or server behavior changes. Full exact-head RIO,
including real TLS/OIDC, mobile, expiry, outages, restarts and native restore,
remains required. Visual checks supplement functional browser checks; physical
Android, manual screen-reader and independent human acceptance #50 remain HOLD.
Historical causes #51/#60/#64, real accounts/contact, staging and production
remain HOLD. This draft does not grant merge or deployment authority.
