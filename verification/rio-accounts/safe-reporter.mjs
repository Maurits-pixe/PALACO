import { mkdir, writeFile } from 'node:fs/promises';

const CASES = new Map([
  ['RIO-E2E-01', 'Two real users have separate sessions and account data'],
  ['RIO-E2E-02', 'Unauthenticated and invalid sessions fail closed'],
  ['RIO-E2E-03', 'Invalid credentials create no BFF session'],
  ['RIO-E2E-04', 'Logout invalidates the session without affecting another user'],
  ['RIO-E2E-05', 'Expired sessions no longer authorize account access'],
  ['RIO-DURABLE-01', 'Save actual OIDC sessions privately before BFF restart'],
  ['RIO-DURABLE-02', 'Database outage denies access until controlled BFF recovery'],
  ['RIO-DURABLE-03', 'Restart preserves own sessions and actor-scoped revocation'],
  ['RIO-DURABLE-04', 'Saved revoked cookies stay denied after another BFF restart'],
  ['RIO-MOBILE-01', 'Native consent controls preserve focus and reflow'],
  ['RIO-MOBILE-02', 'Real local draft downloads cannot become account authority'],
  ['RIO-MOBILE-03', 'Own consent uses session CSRF and a fresh choice after CAS conflict'],
  ['RIO-MOBILE-04', 'Real expiry closes consent while preserving the local draft'],
  ['RIO-MOBILE-05', 'Database uncertainty closes the UI until explicit recovery'],
]);
const PHASES = new Set([
  'initial-access', 'authorization-contract', 'real-idp-login',
  'cookie-contract', 'own-account', 'context-isolation', 'invalid-session',
  'invalid-credentials', 'logout-csrf', 'logout', 'expired-session',
  'no-browser-tokens', 'hold-status', 'session-rotation', 'provider-session-preserved',
  'durable-real-login', 'durable-private-state', 'durable-database-outage',
  'durable-database-recovery', 'durable-connection-stays-closed', 'durable-restart-access', 'durable-cross-actor-csrf',
  'durable-native-revocation', 'durable-revocation-after-restart', 'durable-unaffected-actor',
  'mobile-native-semantics', 'mobile-reflow', 'mobile-local-download',
  'mobile-import-rejection', 'mobile-studio-isolation', 'mobile-consent-isolation',
  'mobile-consent-cas', 'mobile-expiry-closure', 'mobile-database-closure', 'mobile-explicit-recovery',
]);

const MOBILE_SURFACES = new Set(['android-emulation', 'desktop-keyboard']);
const DURABLE_PHASES = new Set(['prepare', 'outage', 'revoke', 'verify']);

const FEEDBACK_BUCKETS = new Set(['empty', 'read_failed', 'logout_failed', 'logged_out', 'other', 'unavailable']);

function safeLogoutObservation(annotations) {
  const annotation = annotations.find(item => item.type === 'rio-logout-observation');
  if (typeof annotation?.description !== 'string' || annotation.description.length > 2048) return undefined;
  let source;
  try { source = JSON.parse(annotation.description); } catch { return undefined; }
  if (!source || typeof source !== 'object' || Array.isArray(source)) return undefined;
  const result = {};
  for (const key of ['logoutRequests', 'logoutResponses', 'logoutFailedRequests', 'otherBffPosts', 'pageErrors']) {
    if (!Number.isInteger(source[key]) || source[key] < 0 || source[key] > 1000) return undefined;
    result[key] = source[key];
  }
  for (const key of ['logoutButtonVisibleBefore', 'logoutButtonEnabledBefore', 'logoutButtonVisibleAfter', 'clickCompleted', 'responseMatched']) {
    if (typeof source[key] !== 'boolean') return undefined;
    result[key] = source[key];
  }
  if (!Array.isArray(source.logoutStatuses) || source.logoutStatuses.length > 16 ||
      source.logoutStatuses.some(value => !Number.isInteger(value) || value < 100 || value > 599)) return undefined;
  result.logoutStatuses = source.logoutStatuses;
  if (!FEEDBACK_BUCKETS.has(source.feedbackBucket)) return undefined;
  result.feedbackBucket = source.feedbackBucket;
  return result;
}

// Raw Playwright diagnostics can contain URLs, cookie values or fill arguments.
// This is the only reporter; artifacts contain only fixed IDs and status fields.
export default class SafeReporter {
  results = [];
  suiteErrors = 0;

  constructor(options = {}) {
    if (options.durablePhase !== undefined && !DURABLE_PHASES.has(options.durablePhase)) {
      throw new Error('Unsupported synthetic durable reporter phase');
    }
    if (options.mobileVerification !== undefined && typeof options.mobileVerification !== 'boolean') {
      throw new Error('Unsupported synthetic mobile reporter option');
    }
    if (options.mobileVerification && options.durablePhase) {
      throw new Error('Synthetic browser evidence modes must remain separate');
    }
    this.mobileVerification = options.mobileVerification === true;
    this.durablePhase = options.durablePhase;
  }

  printsToStdio() { return true; }
  onStdOut() {}
  onStdErr() {}
  onError() { this.suiteErrors += 1; }

  onTestEnd(test, result) {
    const id = /^\[(RIO-E2E-0[1-5]|RIO-DURABLE-0[1-4]|RIO-MOBILE-0[1-5])\]/.exec(test.title)?.[1] ?? 'UNKNOWN-CASE';
    const phases = [];
    const failedLines = new Set();
    const walk = steps => {
      for (const step of steps) {
        if (step.error && Number.isInteger(step.location?.line)) failedLines.add(step.location.line);
        if (step.category === 'test.step' && PHASES.has(step.title)) {
          phases.push({ phase: step.title, status: step.error ? 'failed' : 'passed' });
        }
        walk(step.steps ?? []);
      }
    };
    walk(result.steps);
    const projectName = this.mobileVerification ? test.parent?.project()?.name : undefined;
    const surface = MOBILE_SURFACES.has(projectName) ? projectName : 'unknown';
    const row = {
      id,
      title: CASES.get(id) ?? 'Unexpected test case',
      status: result.status,
      durationMs: Math.round(result.duration),
      ...(this.mobileVerification ? { surface } : {}),
      phases,
      failedLines: result.status === 'passed' ? [] : [...failedLines].sort((a, b) => a - b),
      ...(id === 'RIO-E2E-04' ? { logoutObservation: safeLogoutObservation(test.annotations) } : {}),
    };
    this.results.push(row);
    process.stdout.write(`${id}: ${row.status}${row.failedLines.length ? ' (source lines ' + row.failedLines.join(', ') + ')' : ''}\n`);
  }

  async onEnd(result) {
    const summary = {
      schema: 'rio-accounts-browser-evidence/v1',
      status: result.status,
      suiteErrors: this.suiteErrors,
      browser: 'chromium',
      oidcProvider: 'real-keycloak-loopback',
      credentials: 'synthetic-runtime-only',
      productionAccounts: 'HOLD',
      realInvitations: 'HOLD',
      ...(this.durablePhase ? { durablePhase: this.durablePhase } : {}),
      ...(this.mobileVerification ? {
        verificationScope: 'synthetic-browser-emulation',
        physicalAndroidVerified: false,
        manualScreenReaderVerified: false,
      } : {}),
      tests: this.results,
    };
    await mkdir('evidence', { recursive: true });
    const path = this.durablePhase
      ? 'evidence/browser-durable-' + this.durablePhase + '-summary.json'
      : this.mobileVerification
        ? 'evidence/browser-mobile-summary.json'
        : 'evidence/browser-summary.json';
    await writeFile(path, JSON.stringify(summary, null, 2) + '\n', { mode: 0o600 });
    if (this.durablePhase) {
      process.stdout.write('RIO_DURABLE_BROWSER_SUMMARY ' + JSON.stringify(summary) + '\n');
    }
    if (this.mobileVerification) {
      process.stdout.write('RIO_MOBILE_BROWSER_SUMMARY ' + JSON.stringify(summary) + '\n');
    }
    process.stdout.write(`RIO browser verification: ${result.status}\n`);
  }
}
