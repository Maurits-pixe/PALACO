import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

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

assert.match(css, /prefers-reduced-motion/);
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

console.log('GO-6 smoke checks: PASS');
