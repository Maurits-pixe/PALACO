import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const js = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const css = await readFile(new URL('../styles.css', import.meta.url), 'utf8');
const header = await readFile(new URL('../components/header.html', import.meta.url), 'utf8');
const footer = await readFile(new URL('../components/footer.html', import.meta.url), 'utf8');
const headers = await readFile(new URL('../security-headers.conf', import.meta.url), 'utf8');

assert.match(html, /PALACO/);
assert.match(html, /http-equiv="Content-Security-Policy"/);
assert.match(html, /name="referrer" content="no-referrer"/);
for (const route of ['citadels','elixirs','proof','industrie','governance','evolution','identity']) {
  assert.match(html, new RegExp(`#/${route}`));
}
assert.doesNotMatch(html, /(?:src|href)=["']https?:\/\//i);

new Function(js);
assert.match(js, /UNVERIFIED/);
assert.match(js, /No access or authority is granted/);
assert.match(js, /aria-current/);
assert.match(js, /window\.scrollTo\(0, 0\)/);
assert.match(js, /A presentation and interaction layer/);
assert.match(js, /PRESENT — present, explain, guide/);
assert.match(js, /HARA could help each Citadel coordinate shared services/);
assert.match(js, /not a live LA-001 service or established HARA capability/);
assert.match(js, /Cross-Citadel sharing would require an explicit contract and review/);
assert.match(js, /HARA is not being equated with H∆R∆M/);
assert.match(js, /NOT IMPLEMENTED/);
assert.match(js, /function elixirs\(\)/);
assert.match(js, /aria-labelledby="hara-widget-title"/);
assert.match(js, /HARA desk/);
assert.match(js, /Services[\s\S]*Requests[\s\S]*Updates/);
assert.match(js, /This is a static layout concept\. It reads no household data and submits no requests\./);
assert.match(js, /Advance synthetic demo/);
assert.match(js, /data-hara-demo-status role="status" aria-live="polite"/);
assert.match(js, /no reviewer is contacted/);
assert.match(js, /no decision is made and no service action occurs/);
assert.match(js, /<details class="hara-widget__flow">/);
assert.match(js, /How a future request might be handled/);
assert.match(js, /Illustrative workflow only\. No request can be created from this preview\./);
assert.match(js, /An accountable operator or authorized service records approval, refusal/);
assert.match(js, /NO LIVE SERVICE/);
assert.match(js, /else if \(raw === 'elixirs'\) main\.innerHTML = elixirs\(\)/);
assert.match(js, /link\('citadels\/la-001','Explore Locus Amoenus'\)/);
assert.match(js, /link\('proof\/provenance','Inspect provenance overview'\)/);
assert.match(js, /link\('elixirs','View ELIXERS'\)/);
assert.match(js, /navigate public information only; they do not verify identity, grant access, or authorize an action/);
assert.match(js, /Authority[\s\S]*NOT ESTABLISHED/);
assert.match(js, /proposed H∆R∆M-is-Matriarch-of-H∆R∆ relationship is NOT_ESTABLISHED/);
assert.match(js, /production activation is not allowed by this status/i);
assert.doesNotMatch(js, /Orient · Understand · Navigate · Verify · Act/);

assert.match(css, /prefers-reduced-motion/);
assert.match(css, /\.hara-widget__body\{display:grid/);
assert.match(css, /@media\(max-width:760px\)\{\.hara-widget__body\{grid-template-columns:1fr\}/);
assert.match(header, /href="#\/"[^>]*>PALACO/);
assert.match(header, /href="#\/identity"/);
assert.match(footer, /href="#\/"[^>]*>PALACO/);
assert.match(footer, /href="#\/identity"/);

for (const directive of [
  'Content-Security-Policy:',
  "frame-ancestors 'none'",
  'Referrer-Policy: no-referrer',
  'X-Content-Type-Options: nosniff',
  'X-Frame-Options: DENY',
  'Permissions-Policy:',
  'Cross-Origin-Opener-Policy: same-origin'
]) {
  assert.ok(headers.includes(directive), `Missing security directive: ${directive}`);
}

const handlers = {};
const main = { innerHTML: '', focus() {} };
const status = { textContent: 'Demo not started.' };
const demoButton = { dataset: { step: '0' }, disabled: false, textContent: 'Advance synthetic demo' };
const document = {
  addEventListener: (name, handler) => { handlers[name] = handler; },
  querySelector: (selector) => selector === '#main' ? main : selector === '[data-hara-demo-status]' ? status : null,
  querySelectorAll: () => []
};
const window = { addEventListener() {}, scrollTo() {} };
runInNewContext(js, {
  document,
  window,
  location: { hash: '#/elixirs' },
  fetch: () => { throw new Error('The HARA demo must not make network requests.'); }
});
assert.match(main.innerHTML, /HARA desk/);
for (const expected of [
  'Demo 1 of 3 — an example request would be prepared; it is not submitted.',
  'Demo 2 of 3 — an authorized local review would be required; no reviewer is contacted.',
  'Demo 3 of 3 — no decision is made and no service action occurs.'
]) {
  handlers.click({ target: { closest: (selector) => selector === '[data-hara-demo]' ? demoButton : null } });
  assert.equal(status.textContent, expected);
}
assert.equal(demoButton.disabled, true);
assert.equal(demoButton.textContent, 'Synthetic demo complete');

console.log('GO-6 smoke checks: PASS');
