import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const js = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const css = await readFile(new URL('../styles.css', import.meta.url), 'utf8');
assert.match(html, /PALACO/);
for (const route of ['citadels','elixirs','proof','industrie','governance','evolution','identity']) assert.match(html, new RegExp(`#/${route}`));
assert.match(js, /UNVERIFIED/);
assert.match(js, /No access or authority is granted/);
assert.match(css, /prefers-reduced-motion/);
console.log('GO-6 smoke checks: PASS');
