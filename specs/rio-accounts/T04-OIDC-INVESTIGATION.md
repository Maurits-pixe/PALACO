# T04 — Focused synthetic OIDC readiness investigation

Status: ENGINEERING INVESTIGATION / SYNTHETIC_ONLY. [Issue #51](https://github.com/Maurits-pixe/PALACO/issues/51) remains open; a unique cause is not established.

The baseline `202ba6cba22fa07829c4595dd79216dcd4580ed1` passed both full account workflows. Earlier account-readiness failures are preserved as negative evidence. A successful callback to the home page occurs after the server commits the synthetic session. The page then reads its own account and its consent receipt; a failed or uncertain receipt check can clear the account display again. Therefore a missing displayed identity does not by itself identify an OIDC verifier failure.

## Bounded repetition

After the existing real database-outage and controlled-recovery case, CI executes exactly eight repetitions of `RIO-DURABLE-01`. Each uses fresh browser contexts for alpha, alpha peer and beta and actual Keycloak sign-in, private session saving, cookie and own-account checks. This adds 24 fictional logins before ordinary preparation and the existing restart, revocation, mobile and backup/restore tests.

The [Playwright CLI](https://playwright.dev/docs/test-cli) distinguishes repetition from retry. The command keeps retries at zero, one worker and the existing timeouts; its first failure stops the probe and fails CI. It never reruns a failed action silently. Each probe round exclusively creates its private snapshot, verifies the saved values, closes its contexts and removes only the snapshot it created. A pre-existing snapshot remains protected: a failed exclusive create never authorizes its removal. Ordinary preparation then creates and retains its own fresh snapshot, so the later revocation proof does not use older probe sessions.

The probe retains the 30-second idle and 60-second absolute session limits, fixed loopback origins, purpose and owner checks, current test assertions, bounded database records, private credentials and final cleanup. It creates no real account, contact, device trust, hosting resource or execution authority.

## Failure evidence and interpretation

Only an allowed synthetic actor/stage/page category, known account/consent endpoint statuses, request-failure booleans and a fixed feedback category may enter sanitized failure evidence. URLs, headers, bodies, credential values, raw DOM text and raw errors remain private.

Eight successful repetitions are eight observations in this fixture. They are not a statistical reliability claim, an independent acceptance, a physical-phone test or a cause-specific repair. The original issue remains open until failure evidence supports a concrete diagnosis and an appropriate regression check. Human acceptance, ACCOUNT-1, T05–T08, merge and production retain their separate HOLD gates.

## Mobile navigation and VORM9EVIN9 continuation

The later PR-head observation at Android RIO-MOBILE-02's initial page.goto occurred
within about 1.1 seconds, before an OIDC action. The root route serves embedded
HTML directly and does not load an account from storage. This is distinct from
the original missing account after callback; neither historical cause is proven.

Mobile login now observes each page independently with a fixed stage, bounded
main-document / own-account / consent HTTP statuses, request-failure booleans,
a fixed browser error category and visibility/feedback categories. The collector
records only a failed login, stops its listeners in finally, and rethrows the
original error. It never publishes URLs, credentials, headers, request/response
bodies, raw error text or arbitrary DOM values.

A controlled browser regression refuses exactly the initial main navigation.
It requires one failed attempt, no OIDC/account traffic, no session cookie,
a connection-refused observation and no automatic retry. After removing this
controlled refusal, an explicit fresh login must still pass the real Keycloak,
PKCE, own-account, consent and closed-authority checks.

After the original durable phases, CI repeats the Android RIO-MOBILE-02 case
exactly eight times with fresh test contexts, one worker, zero retries and the
existing timeouts. Its first failure stops the probe and fails CI. The ordinary
mobile suite and actual database backup/restore remain separate required checks.
Repetition may expose a fault category; passing repetitions do not prove the
historical cause is fixed.

VORM9EVIN9 presentation follows the existing RIO identity and the
[source persona](https://github.com/Maurits-pixe/PALACO-Citadel/blob/6774682f0c34c3bc45e02768980347b7117b3d3d/.github/agents/palaco-vorm9evin9.agent.md):
a semantic three-step route, generous touch targets, narrow-screen reflow,
keyboard access and plain phase guidance. These links scroll within the page;
they do not log in, grant consent, create accounts or confer authority. The
existing live feedback region remains the single announcement surface.

No identity-service, Rust authorization/storage rule, token/cookie/session
lifetime, TLS exception, callback assertion or retry policy is relaxed.
Personal accounts, staging, contact, production and independent human acceptance
remain HOLD. The source investigation stays open until observed evidence
supports a cause-specific correction.
