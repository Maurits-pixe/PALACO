import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { applyFixtureEvent, digestWorldManifest, normalizeWorldManifest, validateWorldManifest } from '../src/world.js';

const manifest = JSON.parse(fs.readFileSync(new URL('../src/manifest.json', import.meta.url), 'utf8'));

test('EVA fixture has explicit design-only and non-authoritative boundaries', () => {
  assert.equal(validateWorldManifest(manifest).state, 'STRUCTURALLY_VALID');
  assert.equal(manifest.status, 'DESIGN_DRAFT');
  assert.equal(manifest.engine.authority, 'NON_AUTHORITATIVE');
  assert.equal(manifest.lifecycle.execution_state, 'NOT_AUTHORIZED');
  assert.equal(manifest.visual_reference.type, 'CONCEPT_DESIGN_REFERENCE');
  assert.equal(manifest.visual_reference.constitutional_authority, false);
});

test('missing Citadel binding remains incomplete', () => {
  const candidate = structuredClone(manifest);
  delete candidate.citadel.binding_id;
  assert.equal(validateWorldManifest(candidate).state, 'INCOMPLETE');
});

test('duplicate region or landmark IDs are rejected', () => {
  const candidate = structuredClone(manifest);
  candidate.structure.landmarks[0].id = candidate.structure.regions[0].id;
  assert.equal(validateWorldManifest(candidate).state, 'INVALID');
});

test('unknown manifest fields are rejected by the schema stub', () => {
  const candidate = structuredClone(manifest);
  candidate.unreviewedAuthority = true;
  assert.equal(validateWorldManifest(candidate).state, 'INVALID');
});

test('manifest cannot promote design into activation or authority', () => {
  const candidate = structuredClone(manifest);
  candidate.lifecycle.execution_state = 'AUTHORIZED';
  assert.equal(validateWorldManifest(candidate).state, 'INVALID');
});

test('missing provenance remains invalid rather than being repaired', () => {
  const candidate = structuredClone(manifest);
  delete candidate.provenance.source_class;
  assert.equal(validateWorldManifest(candidate).state, 'INCOMPLETE');
});

test('unknown world identity is reported as a conflict', () => {
  const candidate = structuredClone(manifest);
  candidate.world.id = 'WORLD-OTHER-001';
  assert.equal(validateWorldManifest(candidate).state, 'CONFLICT');
});

test('normalization is deterministic and does not mutate the source', () => {
  const candidate = structuredClone(manifest);
  const before = JSON.stringify(candidate);
  const first = normalizeWorldManifest(candidate);
  const second = normalizeWorldManifest(candidate);
  assert.equal(first, second);
  assert.equal(JSON.stringify(candidate), before);
});

test('normalized SHA-256 digest is deterministic and changes with fixture content', async () => {
  const candidate = structuredClone(manifest);
  const before = JSON.stringify(candidate);
  const first = await digestWorldManifest(candidate);
  const second = await digestWorldManifest(candidate);
  assert.match(first, /^[a-f0-9]{64}$/);
  assert.equal(first, second);
  assert.equal(JSON.stringify(candidate), before);

  const reordered = Object.fromEntries(Object.entries(candidate).reverse());
  assert.equal(await digestWorldManifest(reordered), first);

  const changed = structuredClone(candidate);
  changed.world.sequence += 1;
  assert.notEqual(await digestWorldManifest(changed), first);
});

test('fingerprint reports unavailable crypto instead of a success-shaped fallback', async () => {
  await assert.rejects(
    digestWorldManifest(manifest, null),
    /Web Crypto SHA-256 is unavailable/,
  );
});

test('fixture events advance monotonically and reject duplicates and gaps', () => {
  const initial = { sequence: 41, validationState: 'UNKNOWN', events: [], issues: [] };
  const next = { sequence: 42, eventType: 'RIO_SIGNAL_RECEIVED', region: 'PROOF', validationState: 'UNKNOWN', traceRef: 'synthetic:eva:42' };
  const advanced = applyFixtureEvent(initial, next);
  assert.equal(advanced.sequence, 42);
  assert.equal(advanced.validationState, 'UNKNOWN');
  assert.equal(advanced.events.length, 1);
  assert.equal(applyFixtureEvent(advanced, next).transportState, 'DUPLICATE');
  assert.equal(applyFixtureEvent(initial, { ...next, sequence: 44 }).transportState, 'CONFLICT');
});

test('malformed fixture events are rejected without advancing sequence', () => {
  const initial = { sequence: 41, validationState: 'UNKNOWN', events: [], issues: [] };
  const valid = { sequence: 42, eventType: 'RIO_SIGNAL_RECEIVED', region: 'PROOF', validationState: 'UNKNOWN', traceRef: 'synthetic:eva:42' };
  for (const event of [
    { ...valid, region: 'UNKNOWN_REGION' },
    { ...valid, validationState: 'AUTHORIZED' },
    { ...valid, traceRef: '' },
    { ...valid, sequence: 0 },
  ]) {
    const result = applyFixtureEvent(initial, event);
    assert.equal(result.transportState, 'INVALID');
    assert.equal(result.sequence, initial.sequence);
    assert.equal(result.events.length, 0);
  }
});

test('preview source has no live transport, external write, or activation path', () => {
  for (const file of ['../src/App.vue', '../src/world.js', '../src/animation.js']) {
    const source = fs.readFileSync(new URL(file, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /\b(fetch|EventSource|WebSocket)\b/);
    assert.doesNotMatch(source, /\b(activate|publish|execute)\s*\(/i);
  }
});

test('hero reference image reserves layout space and decodes asynchronously at high priority', () => {
  const app = fs.readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const image = app.match(/<img\s+class="reference-image"[\s\S]*?\/>/)?.[0];

  assert.ok(image, 'EVA reference image should remain the dashboard hero visual.');
  assert.match(image, /width="1312"/);
  assert.match(image, /height="1199"/);
  assert.match(image, /decoding="async"/);
  assert.match(image, /fetchpriority="high"/);
});

test('static preview headers deny external content, embedding, and device permissions', () => {
  const headers = fs.readFileSync(new URL('../public/_headers', import.meta.url), 'utf8');
  assert.match(headers, /Content-Security-Policy: default-src 'self'/);
  assert.match(headers, /object-src 'none'/);
  assert.match(headers, /frame-ancestors 'none'/);
  assert.match(headers, /form-action 'none'/);
  assert.match(headers, /X-Content-Type-Options: nosniff/);
  assert.match(headers, /X-Frame-Options: DENY/);
  assert.match(headers, /Referrer-Policy: no-referrer/);
  assert.match(headers, /Permissions-Policy: camera=\(\), geolocation=\(\), microphone=\(\)/);
});

test('Vercel applies the same strict security headers to deployed routes', () => {
  const config = JSON.parse(fs.readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'));
  const route = config.headers.find(entry => entry.source === '/(.*)');
  assert.ok(route, 'Vercel must apply the security policy to every route.');
  const headers = Object.fromEntries(route.headers.map(({ key, value }) => [key, value]));
  const staticHeaders = Object.fromEntries(
    fs.readFileSync(new URL('../public/_headers', import.meta.url), 'utf8')
      .split('\n')
      .map(line => line.trim())
      .filter(line => line && !line.startsWith('/*'))
      .map(line => {
        const separator = line.indexOf(':');
        return [line.slice(0, separator), line.slice(separator + 1).trim()];
      }),
  );

  assert.equal(config.outputDirectory, 'dist');
  assert.deepEqual(staticHeaders, headers);
  assert.equal(headers['Content-Security-Policy'],
    "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self'; form-action 'none'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'");
  assert.equal(headers['Permissions-Policy'], 'camera=(), geolocation=(), microphone=()');
  assert.equal(headers['Referrer-Policy'], 'no-referrer');
  assert.equal(headers['X-Content-Type-Options'], 'nosniff');
  assert.equal(headers['X-Frame-Options'], 'DENY');
});

test('generated schema validator does not require runtime code evaluation', () => {
  const validator = fs.readFileSync(new URL('../src/validate-manifest.generated.js', import.meta.url), 'utf8');
  assert.doesNotMatch(validator, /\bnew Function\b|\beval\s*\(|\brequire\s*\(/);
});
