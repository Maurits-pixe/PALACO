import { CATALOG } from './catalog.js';
import { VerificationFault, waitWithAbort, abortReason } from './fault.js';

export const VERIFICATION_TIMEOUT_MS = 5000;
export const VERIFICATION_VALIDITY_MS = 60000;
export const MAX_METADATA_BYTES = 64 * 1024;

const IMPOSSIBLE_CODES = new Set(['TIMEOUT', 'TRANSPORT', 'BODY_READ', 'PARSE_UNAVAILABLE', 'REDIRECT', 'INTERNAL']);

export function validateOrigin(input) {
  if (typeof input !== 'string' || !input) return { ok: false, error: 'Vul een HTTPS-origin in.' };
  let url;
  try { url = new URL(input); } catch { return { ok: false, error: 'Ongeldige URL.' }; }
  if (url.protocol !== 'https:') return { ok: false, error: 'Gebruik uitsluitend HTTPS.' };
  if (url.username || url.password) return { ok: false, error: 'Een origin mag geen gebruikersgegevens bevatten.' };
  if (input !== url.origin) return { ok: false, error: 'URL mag geen pad, query of fragment bevatten. Gebruik alleen de origin.' };
  return { ok: true, origin: url.origin };
}

// State is supplied by the Vue layer. Controllers, identity tokens and launch
// grants remain private and are never derived from editable/display state.
export function createVerifier({
  modules,
  parseJson,
  fetchImpl = (...args) => globalThis.fetch(...args),
  now = () => performance.now(),
  wallNow = () => Date.now(),
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = id => clearTimeout(id),
  openWindow = (url, target, features) => window.open(url, target, features)
}) {
  if (typeof parseJson !== 'function') throw new TypeError('An abortable JSON parser is required.');
  const definitions = new Map(CATALOG.map(item => [item.id, item]));
  const attempts = new Map();
  const grants = new Map();
  let generation = 0n;
  let disposed = false;
  const owns = (module, attempt) => !disposed && attempts.get(module) === attempt;

  function retire(module, code = 'SUPERSEDED') {
    const attempt = attempts.get(module);
    attempts.delete(module); // Revoke ownership before aborting any continuation.
    grants.delete(module);
    if (attempt) {
      clearTimer(attempt.timeoutTimer);
      clearTimer(attempt.expiryTimer);
      attempt.snapshot.controller.abort(new VerificationFault(code));
    }
  }

  function reset(module) {
    module.savedUrl = null;
    module.status = 'unconfigured';
    module.error = '';
    module.errorCode = null;
    module.isVerifying = false;
    module.currentCheckId = null;
    module.lastCheck = null;
  }

  function changeInput(module, value) {
    if (disposed) return;
    retire(module);
    reset(module);
    module.inputUrl = value;
    const validation = validateOrigin(value);
    module.isValid = validation.ok;
    module.error = value && !validation.ok ? validation.error : '';
  }

  function cancel(module) {
    if (disposed) return;
    retire(module, 'CANCELLED');
    reset(module);
    module.isValid = validateOrigin(module.inputUrl).ok;
    module.error = 'Controle geannuleerd. Je kunt opnieuw verifiëren.';
  }

  function guard(module, attempt) {
    if (!owns(module, attempt)) throw new VerificationFault('SUPERSEDED');
    if (attempt.snapshot.controller.signal.aborted) throw abortReason(attempt.snapshot.controller.signal);
    if (now() >= attempt.snapshot.deadline) {
      const error = new VerificationFault('TIMEOUT');
      attempt.snapshot.controller.abort(error);
      throw error;
    }
    // Direct caller changes are also rejected; UI changes use changeInput.
    if (module.inputUrl !== attempt.snapshot.origin) throw new VerificationFault('SUPERSEDED');
  }

  async function readBody(response, module, attempt) {
    if (!response.body) throw new VerificationFault('JSON_INVALID');
    const signal = attempt.snapshot.controller.signal;
    const reader = response.body.getReader();
    const chunks = [];
    let total = 0;
    let completed = false;
    try {
      while (true) {
        guard(module, attempt);
        const { done, value } = await waitWithAbort(reader.read(), signal);
        guard(module, attempt);
        if (done) { completed = true; break; }
        total += value.byteLength;
        if (total > MAX_METADATA_BYTES) throw new VerificationFault('BODY_LIMIT');
        chunks.push(value);
      }
      const bytes = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
      catch { throw new VerificationFault('JSON_INVALID'); }
    } finally {
      if (!completed) void reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  async function verify(module) {
    if (disposed) return;
    retire(module);
    reset(module);
    const validation = validateOrigin(module.inputUrl);
    module.isValid = validation.ok;
    if (!validation.ok) { module.error = validation.error; module.errorCode = 'ORIGIN'; return; }
    const definition = definitions.get(module.id);
    if (!definition?.origins.includes(validation.origin)) {
      module.status = 'not_approved';
      module.error = 'Deze origin staat niet in de configuratie voor deze module.';
      module.errorCode = 'NOT_APPROVED';
      return;
    }
    const snapshot = Object.freeze({
      id: (++generation).toString(), origin: validation.origin,
      expectedId: definition.expectedId, controller: new AbortController(),
      deadline: now() + VERIFICATION_TIMEOUT_MS
    });
    const attempt = { snapshot, timeoutTimer: null, expiryTimer: null };
    attempts.set(module, attempt);
    module.currentCheckId = snapshot.id;
    module.savedUrl = snapshot.origin;
    module.status = 'checking';
    module.isVerifying = true;
    attempt.timeoutTimer = setTimer(() => {
      if (owns(module, attempt)) snapshot.controller.abort(new VerificationFault('TIMEOUT'));
    }, VERIFICATION_TIMEOUT_MS);
    let phase = 'fetch';
    try {
      guard(module, attempt);
      const response = await waitWithAbort(fetchImpl(`${snapshot.origin}/.well-known/palaco-app.json`, {
        method: 'GET', redirect: 'error', credentials: 'omit', cache: 'no-store',
        signal: snapshot.controller.signal, headers: { Accept: 'application/json' }
      }), snapshot.controller.signal);
      guard(module, attempt);
      if (response.redirected) throw new VerificationFault('REDIRECT');
      if (response.status !== 200) throw new VerificationFault('HTTP', `HTTP-status ${response.status}.`);
      phase = 'body';
      const text = await readBody(response, module, attempt);
      guard(module, attempt);
      phase = 'parse';
      const data = await waitWithAbort(parseJson(text, snapshot.controller.signal), snapshot.controller.signal);
      guard(module, attempt);
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new VerificationFault('SCHEMA_OBJECT');
      if (typeof data.appId !== 'string') throw new VerificationFault('SCHEMA_APP_ID');
      if (typeof data.status !== 'string') throw new VerificationFault('SCHEMA_STATUS');
      if (data.appId !== snapshot.expectedId) throw new VerificationFault('IDENTITY');
      guard(module, attempt); // Last acceptance check covers parse + validation.
      const verifiedAt = now();
      if (verifiedAt >= snapshot.deadline) throw new VerificationFault('TIMEOUT');
      const displayTime = wallNow();
      const grant = Object.freeze({
        origin: snapshot.origin, checkId: snapshot.id,
        deadline: verifiedAt + VERIFICATION_VALIDITY_MS,
        wallDeadline: displayTime + VERIFICATION_VALIDITY_MS
      });
      grants.set(module, grant);
      module.status = 'verified';
      module.lastCheck = { time: displayTime, expires: grant.wallDeadline, result: 'success',
        receivedId: data.appId, receivedStatus: data.status, origin: snapshot.origin, checkId: snapshot.id };
      attempt.expiryTimer = setTimer(() => {
        if (owns(module, attempt) && grants.get(module) === grant) refresh(module);
      }, VERIFICATION_VALIDITY_MS);
    } catch (error) {
      if (!owns(module, attempt)) return;
      // Unexpected direct edits cannot make an old snapshot appear verified.
      if (module.inputUrl !== snapshot.origin) {
        retire(module);
        reset(module);
        module.isValid = validateOrigin(module.inputUrl).ok;
        return;
      }
      const fault = snapshot.controller.signal.aborted ? abortReason(snapshot.controller.signal)
        : error instanceof VerificationFault ? error
        : new VerificationFault(phase === 'fetch' ? 'TRANSPORT' : phase === 'body' ? 'BODY_READ' : phase === 'parse' ? 'JSON_INVALID' : 'INTERNAL');
      grants.delete(module);
      module.status = IMPOSSIBLE_CODES.has(fault.code) ? 'impossible' : 'failed';
      module.error = fault.message;
      module.errorCode = fault.code;
      module.lastCheck = { time: wallNow(), result: 'fail', reason: fault.message,
        code: fault.code, origin: snapshot.origin, checkId: snapshot.id };
      snapshot.controller.abort(fault);
    } finally {
      clearTimer(attempt.timeoutTimer); // Only this attempt's timer.
      if (owns(module, attempt)) module.isVerifying = false;
    }
  }

  function expire(module) {
    grants.delete(module);
    const attempt = attempts.get(module);
    if (attempt) clearTimer(attempt.expiryTimer);
    if (module.status === 'verified') module.status = 'expired';
  }

  function refresh(module) {
    const grant = grants.get(module);
    if (grant && (now() >= grant.deadline || wallNow() >= grant.wallDeadline)) expire(module);
  }

  function refreshAll() {
    if (!disposed) for (const module of modules) refresh(module);
  }

  // Returning from focus/visibility/BFCache conservatively requires a new
  // check. This closes browser sleep/clock differences without extending TTL.
  function suspend() {
    if (disposed) return;
    for (const module of modules) {
      if (module.isVerifying) cancel(module);
      expire(module);
    }
  }

  function remainingSeconds(module) {
    const grant = grants.get(module);
    if (!grant || module.status !== 'verified') return 0;
    return Math.max(0, Math.ceil(Math.min(grant.deadline - now(), grant.wallDeadline - wallNow()) / 1000));
  }

  function open(module) {
    if (disposed) return false;
    refresh(module);
    const grant = grants.get(module);
    const validation = validateOrigin(module.inputUrl);
    if (!grant || module.status !== 'verified' || !validation.ok || validation.origin !== grant.origin) return false;
    const definition = definitions.get(module.id);
    if (!definition?.origins.includes(grant.origin)) return false;
    // Open the immutable verified origin, never a caller-edited savedUrl.
    openWindow(grant.origin, '_blank', 'noopener,noreferrer');
    return true;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    for (const module of modules) {
      retire(module, 'DISPOSED');
      reset(module);
    }
  }

  return Object.freeze({ changeInput, verify, cancel, open, refreshAll, suspend, remainingSeconds, dispose });
}
