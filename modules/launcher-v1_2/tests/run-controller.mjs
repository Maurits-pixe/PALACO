import assert from 'node:assert/strict';
import http from 'node:http';
import { performance } from 'node:perf_hooks';
import { createVerifier, MAX_METADATA_BYTES } from '../src/verifier.js';
import { createModuleStates, CATALOG } from '../src/catalog.js';
import { parseMetadataText } from '../src/json-parser.js';
import { createReport } from './report.mjs';

const report = createReport('controller', import.meta.url, [
  'Controller tests execute the actual ESM core with injected clock/network/parser dependencies; no Vue stubs or source rewriting.',
  'The one native Fetch test remaps the allowed HTTPS origin only at the injected fetch boundary to loopback HTTP. No browser CORS/TLS claim for that test.',
  'Worker execution, UI interaction and TLS are tested in separate suites. Full DRAFT contract unavailable.'
]);
const pump = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function clock() {
  let next = 1;
  const timers = new Map();
  return {
    mono: 0, wall: 1000, timers,
    set(fn, ms) { const id = next++; timers.set(id, { at: this.mono + ms, fn }); return id; },
    clear(id) { timers.delete(id); },
    advance(ms) {
      const end = this.mono + ms;
      while (true) {
        const first = [...timers].filter(([, timer]) => timer.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!first) break;
        this.wall += first[1].at - this.mono; this.mono = first[1].at;
        timers.delete(first[0]); first[1].fn();
      }
      this.wall += end - this.mono; this.mono = end;
    }
  };
}
function subject(fetchImpl = async () => response(), parseJson = async text => parseMetadataText(text), realTime = false) {
  const c = clock();
  const modules = createModuleStates();
  const opens = [];
  const v = createVerifier({ modules, fetchImpl, parseJson,
    now: realTime ? () => performance.now() : () => c.mono,
    wallNow: realTime ? () => Date.now() : () => c.wall,
    setTimer: realTime ? setTimeout : c.set.bind(c),
    clearTimer: realTime ? clearTimeout : c.clear.bind(c),
    openWindow: (...args) => opens.push(args) });
  const m = modules[0];
  v.changeInput(m, 'https://localhost:5174');
  return { c, modules, m, v, opens };
}
function response(data = { appId: 'aether', status: 'ready' }, status = 200) {
  return new Response(JSON.stringify(data), { status });
}
const snapshot = m => ({ status: m.status, busy: m.isVerifying, id: m.currentCheckId,
  savedUrl: m.savedUrl, code: m.errorCode, lastCheck: m.lastCheck });

for (const [id, data, expected, code] of [
  ['SCHEMA-VALID', { appId: 'aether', status: 'ready' }, 'verified', null],
  ['SCHEMA-MISSING-STATUS', { appId: 'aether' }, 'failed', 'SCHEMA_STATUS'],
  ['SCHEMA-STATUS-TYPE', { appId: 'aether', status: 7 }, 'failed', 'SCHEMA_STATUS'],
  ['SCHEMA-APP-ID-TYPE', { appId: 7, status: 'ready' }, 'failed', 'SCHEMA_APP_ID'],
  ['SCHEMA-NON-OBJECT', null, 'failed', 'SCHEMA_OBJECT'],
  ['IDENTITY-MISMATCH', { appId: 'bastion', status: 'ready' }, 'failed', 'IDENTITY']
]) await report.check(id, async () => {
  const s = subject(async () => response(data));
  try { await s.v.verify(s.m); assert.equal(s.m.status, expected); assert.equal(s.m.errorCode, code); return snapshot(s.m); }
  finally { s.v.dispose(); }
});

for (const [id, url, status] of [
  ['ORIGIN-PATH', 'https://localhost:5174/somepath', 'unconfigured'],
  ['ORIGIN-QUERY', 'https://localhost:5174?x=1', 'unconfigured'],
  ['ORIGIN-FRAGMENT', 'https://localhost:5174#x', 'unconfigured'],
  ['ORIGIN-CREDENTIALS', 'https://user:pass@localhost:5174', 'unconfigured'],
  ['ORIGIN-HTTP', 'http://localhost:5174', 'unconfigured'],
  ['ORIGIN-NOT-APPROVED', 'https://unapproved.invalid', 'not_approved']
]) await report.check(id, async () => {
  let calls = 0;
  const s = subject(async () => { calls++; return response(); });
  try { s.v.changeInput(s.m, url); await s.v.verify(s.m); assert.equal(calls, 0); assert.equal(s.m.status, status); return { calls, ...snapshot(s.m) }; }
  finally { s.v.dispose(); }
});

await report.check('ALL-THREE-MODULES', async () => {
  const modules = createModuleStates();
  const v = createVerifier({ modules, parseJson: async text => parseMetadataText(text),
    fetchImpl: async url => response({ appId: CATALOG.find(item => url.startsWith(item.origins[0])).expectedId, status: 'ready' }),
    openWindow: () => {} });
  try {
    for (let i = 0; i < modules.length; i++) { v.changeInput(modules[i], CATALOG[i].origins[0]); await v.verify(modules[i]); }
    assert.deepEqual(modules.map(m => m.status), ['verified', 'verified', 'verified']);
    return modules.map(snapshot);
  } finally { v.dispose(); }
}, 'actual core, real monotone clock; deterministic metadata fixtures');

await report.check('HTTP-NON-200', async () => {
  const s = subject(async () => response({}, 503));
  try { await s.v.verify(s.m); assert.equal(s.m.errorCode, 'HTTP'); assert.equal(s.m.status, 'failed'); return snapshot(s.m); }
  finally { s.v.dispose(); }
});
await report.check('JSON-MALFORMED', async () => {
  const s = subject(async () => new Response('{broken'));
  try { await s.v.verify(s.m); assert.equal(s.m.errorCode, 'JSON_INVALID'); return snapshot(s.m); }
  finally { s.v.dispose(); }
});
await report.check('BODY-SIZE-LIMIT', async () => {
  const s = subject(async () => new Response('x'.repeat(MAX_METADATA_BYTES + 1)));
  try { await s.v.verify(s.m); assert.equal(s.m.errorCode, 'BODY_LIMIT'); return snapshot(s.m); }
  finally { s.v.dispose(); }
});
await report.check('TIMEOUT-NO-HEADERS', async () => {
  const s = subject(() => new Promise(() => {}));
  try { const pending = s.v.verify(s.m); s.c.advance(5000); await pending; assert.equal(s.m.status, 'impossible'); assert.equal(s.m.errorCode, 'TIMEOUT'); return snapshot(s.m); }
  finally { s.v.dispose(); }
});
await report.check('TIMEOUT-PARSE-PENDING', async () => {
  let signal;
  const s = subject(undefined, (_text, suppliedSignal) => { signal = suppliedSignal; return new Promise(() => {}); });
  try {
    const pending = s.v.verify(s.m); await pump(); assert.ok(signal);
    s.c.advance(5000); await pending;
    assert.equal(signal.aborted, true); assert.equal(s.m.errorCode, 'TIMEOUT'); return snapshot(s.m);
  } finally { s.v.dispose(); }
});
await report.check('TIMEOUT-DELAYED-WATCHDOG', async () => {
  const body = deferred();
  const s = subject(undefined, () => body.promise);
  try {
    const pending = s.v.verify(s.m); await pump();
    s.c.mono = 5000; // Deliberately do not dispatch the queued timeout.
    body.resolve({ appId: 'aether', status: 'ready' }); await pending;
    assert.equal(s.m.errorCode, 'TIMEOUT'); assert.notEqual(s.m.status, 'verified'); return snapshot(s.m);
  } finally { s.v.dispose(); }
});

await report.check('TIMEOUT-SLOW-BODY', async () => {
  const timers = new Set();
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'content-type': 'application/json', connection: 'close' }); res.flushHeaders();
    const timer = setTimeout(() => { timers.delete(timer); res.end(JSON.stringify({ appId: 'aether', status: 'ready' })); }, 5200);
    timers.add(timer);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const target = `http://127.0.0.1:${server.address().port}/.well-known/palaco-app.json`;
  const s = subject((_url, options) => fetch(target, options), undefined, true);
  try {
    const start = performance.now(); await s.v.verify(s.m); const elapsedMs = performance.now() - start;
    assert.equal(s.m.status, 'impossible'); assert.equal(s.m.errorCode, 'TIMEOUT');
    assert.equal(s.m.lastCheck.result, 'fail'); return { elapsedMs, bodyDelayMs: 5200, ...snapshot(s.m) };
  } finally {
    s.v.dispose(); for (const timer of timers) clearTimeout(timer);
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
}, 'native Node Fetch and body consumption; real 5200ms delay; loopback HTTP transport remap');

await report.check('RACE-STALE-SUCCESS-AND-FINALLY', async () => {
  const oldJson = deferred(), secondHeaders = deferred(); let parseCalls = 0, fetchCalls = 0;
  const s = subject(() => ++fetchCalls === 1 ? Promise.resolve(response()) : secondHeaders.promise,
    text => ++parseCalls === 1 ? oldJson.promise : Promise.resolve(parseMetadataText(text)));
  try {
    const first = s.v.verify(s.m); await pump(); assert.equal(parseCalls, 1); const firstId = s.m.currentCheckId;
    oldJson.resolve({ appId: 'aether', status: 'ready' });
    s.v.changeInput(s.m, 'https://aether.hoofdkantoor.info');
    const second = s.v.verify(s.m); const secondId = s.m.currentCheckId;
    await first;
    assert.notEqual(firstId, secondId); assert.equal(s.m.status, 'checking'); assert.equal(s.m.isVerifying, true);
    const afterOldContinuation = snapshot(s.m);
    secondHeaders.resolve(response({ appId: 'aether', status: 'second' })); await second;
    assert.equal(s.m.lastCheck.origin, 'https://aether.hoofdkantoor.info'); assert.equal(s.m.lastCheck.receivedStatus, 'second');
    return { firstId, secondId, afterOldContinuation, completed: snapshot(s.m) };
  } finally { s.v.dispose(); }
});
await report.check('CHECK-ID-COLLISION', async () => {
  const s = subject(() => new Promise(() => {}));
  try {
    const first = s.v.verify(s.m); const firstId = s.m.currentCheckId;
    const second = s.v.verify(s.m); const secondId = s.m.currentCheckId;
    await first; assert.notEqual(firstId, secondId); assert.equal(s.c.wall, 1000);
    s.v.cancel(s.m); await second;
    return { firstId, secondId, sameWallClockMs: s.c.wall };
  } finally { s.v.dispose(); }
});
await report.check('RACE-STALE-FAILURE', async () => {
  const old = deferred(), next = deferred(); let calls = 0;
  const s = subject(() => ++calls === 1 ? old.promise : next.promise);
  try {
    const first = s.v.verify(s.m); const second = s.v.verify(s.m);
    old.reject(new TypeError('Load failed')); await first;
    assert.equal(s.m.status, 'checking'); assert.equal(s.m.isVerifying, true);
    next.resolve(response()); await second; assert.equal(s.m.status, 'verified'); return snapshot(s.m);
  } finally { s.v.dispose(); }
});
await report.check('INPUT-REVOKES-PENDING-ATTEMPT', async () => {
  let signal;
  const s = subject((_url, options) => { signal = options.signal; return new Promise(() => {}); });
  try {
    const pending = s.v.verify(s.m); s.v.changeInput(s.m, 'https://localhost:5174/somepath'); await pending;
    assert.equal(signal.aborted, true); assert.equal(s.m.status, 'unconfigured'); assert.equal(s.m.isVerifying, false);
    assert.equal(s.v.open(s.m), false); return snapshot(s.m);
  } finally { s.v.dispose(); }
});
await report.check('UNMOUNT-INVALIDATES-LATE-RESULT', async () => {
  const old = deferred(); const s = subject(() => old.promise);
  const pending = s.v.verify(s.m); s.v.dispose(); const retired = snapshot(s.m);
  old.resolve(response()); await pending;
  assert.deepEqual(snapshot(s.m), retired); assert.equal(s.v.open(s.m), false);
  return retired;
});

await report.check('EXPIRY-TIMER', async () => {
  const s = subject();
  try { await s.v.verify(s.m); s.c.advance(60000); assert.equal(s.m.status, 'expired'); assert.equal(s.v.open(s.m), false); return snapshot(s.m); }
  finally { s.v.dispose(); }
});
await report.check('EXPIRY-EXACT-BOUNDARY', async () => {
  const s = subject();
  try {
    await s.v.verify(s.m); s.c.mono = 60000; s.c.wall = 61000;
    assert.equal(s.v.open(s.m), false); assert.equal(s.opens.length, 0); assert.equal(s.m.status, 'expired'); return snapshot(s.m);
  } finally { s.v.dispose(); }
});
await report.check('EXPIRY-CLOCK-ROLLBACK', async () => {
  const s = subject();
  try {
    await s.v.verify(s.m); s.c.mono = 70000; s.c.wall = 500;
    assert.equal(s.v.open(s.m), false); assert.equal(s.opens.length, 0); return snapshot(s.m);
  } finally { s.v.dispose(); }
});
await report.check('RETURN-REQUIRES-REVERIFICATION', async () => {
  const s = subject();
  try { await s.v.verify(s.m); s.v.suspend(); assert.equal(s.m.status, 'expired'); assert.equal(s.v.open(s.m), false); return snapshot(s.m); }
  finally { s.v.dispose(); }
});
await report.check('LAUNCH-USES-VERIFIED-SNAPSHOT', async () => {
  const s = subject();
  try {
    await s.v.verify(s.m); s.m.savedUrl = 'https://unapproved.invalid';
    assert.equal(s.v.open(s.m), true); assert.deepEqual(s.opens, [['https://localhost:5174', '_blank', 'noopener,noreferrer']]);
    s.m.inputUrl = 'https://aether.hoofdkantoor.info'; assert.equal(s.v.open(s.m), false);
    return { opens: s.opens };
  } finally { s.v.dispose(); }
});
await report.check('NETWORK-ERROR-TEXT', async () => {
  const observations = [];
  for (const message of ['Load failed', 'Failed to fetch', 'NetworkError', 'unrelated', 'redirect', '']) {
    const s = subject(async () => { throw new TypeError(message); });
    try { await s.v.verify(s.m); assert.equal(s.m.status, 'impossible'); assert.equal(s.m.errorCode, 'TRANSPORT'); observations.push({ injectedMessage: message, ...snapshot(s.m) }); }
    finally { s.v.dispose(); }
  }
  return observations;
});
await report.check('REDIRECT-REJECTED', async () => {
  let options;
  const s = subject(async (_url, supplied) => { options = supplied; return { status: 200, redirected: true }; });
  try { await s.v.verify(s.m); assert.equal(options.redirect, 'error'); assert.equal(s.m.errorCode, 'REDIRECT'); return snapshot(s.m); }
  finally { s.v.dispose(); }
});
report.finish();
