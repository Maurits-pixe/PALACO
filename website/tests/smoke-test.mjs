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
for (const route of ['citadels','elixirs','proof','industrie','governance','evolution','account']) {
  assert.match(html, new RegExp(`#/${route}`));
}
assert.doesNotMatch(html, /(?:src|href)=["']https?:\/\//i);

new Function(js);
assert.match(js, /UNVERIFIED/);
assert.match(js, /No access or authority is granted/);
assert.match(js, /aria-current/);
assert.match(js, /window\.scrollTo\(0, 0\)/);
assert.match(js, /function account\(\)/);
assert.match(js, /function industrieAdmin\(\)/);
assert.match(js, /4,444/);
assert.match(js, /PREVIEW · NOT CONNECTED/);
assert.match(js, /SYNTHETIC PREVIEW · NO ADMIN BACKEND/);
assert.match(js, /disabled aria-describedby="account-status"/);
assert.match(js, /disabled aria-describedby="admin-status"/);
assert.doesNotMatch(js, /type=["']password["']/i);
assert.doesNotMatch(js, /localStorage|sessionStorage/);
assert.match(html, /connect-src 'none'/);
assert.match(js, /do not collect credentials/i);
assert.match(js, /No estimated or client-maintained count is presented as canonical/);
assert.match(js, /require independent approval/);

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
