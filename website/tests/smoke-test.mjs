import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const js = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const haraRuntime = await readFile(new URL('../hara-runtime.js', import.meta.url), 'utf8');
const css = await readFile(new URL('../styles.css', import.meta.url), 'utf8');
const header = await readFile(new URL('../components/header.html', import.meta.url), 'utf8');
const footer = await readFile(new URL('../components/footer.html', import.meta.url), 'utf8');
const headers = await readFile(new URL('../security-headers.conf', import.meta.url), 'utf8');

assert.match(html, /PALACO/);
assert.match(html, /http-equiv="Content-Security-Policy"/);
assert.match(html, /name="referrer" content="no-referrer"/);
assert.match(html, /hara-runtime\.js" defer><\/script>[\s\S]*app\.js" defer/);
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
assert.match(js, /function elixirs\(requestedView = 'all', requestedCategory = 'all'\)/);
assert.match(js, /aria-labelledby="hara-widget-title"/);
assert.match(js, /HARA desk/);
assert.match(js, /Choose a HARA preview section/);
assert.match(js, /data-hara-view="candidate" aria-controls="hara-candidate-panel" aria-pressed="\$\{view === 'candidate'\}"/);
assert.match(js, /data-hara-panel="candidate"/);
assert.match(js, /Showing the isolated D-012 candidate status only/);
assert.match(js, /const visibleExamples = examples\.filter/);
assert.match(js, /ISOLATED CANDIDATE · 0\.3\.3-d012\.1/);
assert.match(js, /H∆R∆ Hannie agenda · D-012/);
assert.match(js, /STORAGE_EFFECT_DEADLINE_UNSUPPORTED/);
assert.match(js, /Not connected to this website or a live calendar/);
assert.match(js, /Integration and production remain on hold/);
assert.match(js, /role="group" aria-label="Filter proposed service examples"/);
assert.match(js, /data-hara-filter data-category="wellbeing" aria-pressed="\$\{category === 'wellbeing'\}">Care/);
assert.match(js, /data-hara-service data-category="\$\{example\.category\}"/);
assert.match(js, /Showing \$\{visibleExamples\.length\} proposed service example/);
assert.match(js, /Services[\s\S]*Requests[\s\S]*Updates/);
assert.match(js, /This is a static layout concept\. It reads no household data and submits no requests\./);
assert.match(js, /LOCAL SYNTHETIC RUNTIME/);
assert.match(js, /data-hara-runtime-status role="status" aria-live="polite"/);
assert.match(js, /data-hara-runtime-prepare/);
assert.match(js, /data-hara-runtime-review/);
assert.match(js, /data-hara-runtime-close/);
assert.match(js, /data-hara-runtime-reset/);
assert.match(js, /No operator was contacted; no decision or permission was made/);
assert.match(haraRuntime, /Object\.hasOwn\(services, serviceId\)/);
assert.doesNotMatch(haraRuntime, /\b(?:fetch|localStorage|sessionStorage|indexedDB|XMLHttpRequest)\b/);
assert.match(js, /document\.addEventListener\('click'/);
assert.match(js, /<details class="hara-widget__flow">/);
assert.match(js, /How a future request might be handled/);
assert.match(js, /Illustrative workflow only\. No request can be created from this preview\./);
assert.match(js, /An accountable operator or authorized service records approval, refusal/);
assert.match(js, /NO LIVE SERVICE/);
assert.match(js, /params\.get\('view'\) \|\| 'all', params\.get\('category'\) \|\| 'all'/);
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
assert.match(css, /\.hara-widget__views button\[aria-pressed=true\]/);
assert.match(css, /\.hara-widget__filters button\[aria-pressed=true\]/);
assert.match(css, /\.hara-scenario\{display:grid/);
assert.match(css, /\.hara-d012\{display:grid/);
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
let locationHash = '#/elixirs?view=candidate';
const historyEntries = [locationHash];
const location = {
  get hash() { return locationHash; },
  set hash(value) {
    if (value === locationHash) return;
    locationHash = value;
    historyEntries.push(value);
    handlers['window:hashchange']?.();
  }
};
const runtimeStatus = { textContent: '' };
const runtimeService = { value: 'care', disabled: false };
const prepareButton = { disabled: false };
const reviewButton = { disabled: true };
const closeButton = { disabled: true };
const runtimeResetButton = { disabled: true };
const allFilter = { dataset: { category: 'all' }, textContent: 'All examples', pressed: null, setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; } };
const careFilter = { dataset: { category: 'wellbeing' }, textContent: 'Care', pressed: null, setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; } };
const placeFilter = { dataset: { category: 'place' }, textContent: 'Place', pressed: null, setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; } };
const careService = { dataset: { category: 'wellbeing' }, hidden: false };
const maintenanceService = { dataset: { category: 'place' }, hidden: false };
const guideService = { dataset: { category: 'place' }, hidden: false };
const filterStatus = { textContent: 'Showing all 3 proposed service examples.' };
const viewStatus = { textContent: 'Showing all.' };
const overviewView = { dataset: { haraView: 'all' }, pressed: null, setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; } };
const servicesView = { dataset: { haraView: 'services' }, pressed: null, setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; } };
const candidateView = { dataset: { haraView: 'candidate' }, pressed: null, setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; } };
const scenarioView = { dataset: { haraView: 'scenario' }, pressed: null, setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; } };
const servicesPanel = { dataset: { haraPanel: 'services' }, hidden: false };
const candidatePanel = { dataset: { haraPanel: 'candidate' }, hidden: false };
const scenarioPanel = { dataset: { haraPanel: 'scenario' }, hidden: false };
const runtimeWindow = {};
runInNewContext(haraRuntime, {window: runtimeWindow});
const document = {
  addEventListener: (name, handler) => { handlers[name] = handler; },
  querySelector: (selector) => selector === '#main' ? main : selector === '[data-hara-view-status]' ? viewStatus : selector === '[data-hara-filter-status]' ? filterStatus : selector === '[data-hara-runtime-service]' ? runtimeService : selector === '[data-hara-runtime-status]' ? runtimeStatus : selector === '[data-hara-runtime-prepare]' ? prepareButton : selector === '[data-hara-runtime-review]' ? reviewButton : selector === '[data-hara-runtime-close]' ? closeButton : selector === '[data-hara-runtime-reset]' ? runtimeResetButton : null,
  querySelectorAll: (selector) => selector === '[data-hara-service]' ? [careService, maintenanceService, guideService] : selector === '[data-hara-filter]' ? [allFilter, careFilter, placeFilter] : selector === '[data-hara-panel]' ? [servicesPanel, candidatePanel, scenarioPanel] : selector === '[data-hara-view]' ? [overviewView, candidateView] : []
};
const window = { PalacoHaraDemoRuntime: runtimeWindow.PalacoHaraDemoRuntime, addEventListener: (name, handler) => { handlers[`window:${name}`] = handler; }, scrollTo() {} };
runInNewContext(js, {
  document,
  window,
  location,
  URLSearchParams,
  fetch: () => { throw new Error('The HARA demo must not make network requests.'); }
});
assert.match(main.innerHTML, /HARA desk/);
assert.match(main.innerHTML, /data-hara-view="candidate"[^>]*aria-pressed="true"/);
assert.match(main.innerHTML, /data-hara-panel="services"[^>]* hidden>/);
assert.match(main.innerHTML, /data-hara-panel="candidate"[^>]* aria-labelledby="hara-d012-title">/);
assert.match(main.innerHTML, /data-hara-panel="scenario"[^>]* hidden>/);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-view]' ? servicesView : null } });
assert.equal(location.hash, '#/elixirs?view=services');
assert.match(main.innerHTML, /data-hara-view="services"[^>]*aria-pressed="true"/);
assert.match(main.innerHTML, /data-hara-panel="services"[^>]* aria-labelledby="hara-widget-title">/);
assert.match(main.innerHTML, /data-hara-panel="candidate"[^>]* hidden>/);
assert.match(main.innerHTML, /data-hara-panel="scenario"[^>]* hidden>/);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-view]' ? candidateView : null } });
assert.equal(location.hash, '#/elixirs?view=candidate');
assert.match(main.innerHTML, /Showing the isolated D-012 candidate status only\./);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-view]' ? overviewView : null } });
assert.equal(location.hash, '#/elixirs?view=all');
assert.match(main.innerHTML, /data-hara-view="all"[^>]*aria-pressed="true"/);
assert.doesNotMatch(main.innerHTML, /data-hara-panel="(?:services|candidate|scenario)"[^>]* hidden>/);
historyEntries.pop();
locationHash = historyEntries.at(-1);
handlers['window:hashchange']();
assert.equal(location.hash, '#/elixirs?view=candidate');
assert.match(main.innerHTML, /data-hara-view="candidate"[^>]*aria-pressed="true"/);
location.hash = '#/elixirs?view=unknown';
assert.match(main.innerHTML, /data-hara-view="all"[^>]*aria-pressed="true"/);
assert.match(main.innerHTML, /Showing the complete proposal overview\./);
location.hash = '#/elixirs?view=services&category=unknown';
assert.match(main.innerHTML, /data-hara-filter data-category="all" aria-pressed="true"/);
assert.match(main.innerHTML, /Showing all 3 proposed service examples\./);
assert.doesNotMatch(main.innerHTML, /data-hara-service[^>]* hidden>/);
location.hash = '#/elixirs?view=services&category=place';
assert.match(main.innerHTML, /data-hara-filter data-category="place" aria-pressed="true"/);
assert.match(main.innerHTML, /Showing 2 proposed service examples for Place\./);
assert.match(main.innerHTML, /data-category="wellbeing" hidden>/);
assert.doesNotMatch(main.innerHTML, /data-category="place" hidden>/);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-filter]' ? careFilter : null } });
assert.equal(location.hash, '#/elixirs?view=services&category=wellbeing');
assert.match(main.innerHTML, /data-hara-filter data-category="wellbeing" aria-pressed="true"/);
assert.match(main.innerHTML, /Showing 1 proposed service example for Care\./);
assert.doesNotMatch(main.innerHTML, /data-category="wellbeing" hidden>/);
assert.match(main.innerHTML, /data-category="place" hidden>/);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-filter]' ? placeFilter : null } });
assert.equal(location.hash, '#/elixirs?view=services&category=place');
assert.match(main.innerHTML, /data-hara-filter data-category="place" aria-pressed="true"/);
assert.match(main.innerHTML, /Showing 2 proposed service examples for Place\./);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-filter]' ? allFilter : null } });
assert.equal(location.hash, '#/elixirs?view=services');
assert.match(main.innerHTML, /data-hara-filter data-category="all" aria-pressed="true"/);
assert.match(main.innerHTML, /Showing all 3 proposed service examples\./);
historyEntries.pop();
locationHash = historyEntries.at(-1);
handlers['window:hashchange']();
assert.equal(location.hash, '#/elixirs?view=services&category=place');
assert.match(main.innerHTML, /data-hara-filter data-category="place" aria-pressed="true"/);
assert.match(runtimeStatus.textContent, /Synthetic-only demo ready/);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-runtime-prepare]' ? prepareButton : null } });
assert.match(runtimeStatus.textContent, /This is not a request; nothing was sent or stored/);
assert.deepEqual([runtimeService.disabled, prepareButton.disabled, reviewButton.disabled, closeButton.disabled, runtimeResetButton.disabled], [true, true, false, true, false]);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-filter]' ? careFilter : null } });
assert.equal(location.hash, '#/elixirs?view=services&category=wellbeing');
assert.match(runtimeStatus.textContent, /This is not a request; nothing was sent or stored/);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-runtime-review]' ? reviewButton : null } });
assert.match(runtimeStatus.textContent, /No operator was contacted; no decision or permission was made/);
assert.deepEqual([reviewButton.disabled, closeButton.disabled], [true, false]);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-view]' ? candidateView : null } });
assert.equal(location.hash, '#/elixirs?view=candidate');
assert.match(runtimeStatus.textContent, /No operator was contacted; no decision or permission was made/);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-runtime-close]' ? closeButton : null } });
assert.equal(runtimeStatus.textContent, 'Scenario ended without a decision, permission, or service action.');
handlers.click({ target: { closest: (selector) => selector === '[data-hara-runtime-reset]' ? runtimeResetButton : null } });
assert.match(runtimeStatus.textContent, /Synthetic-only demo ready/);
assert.deepEqual([runtimeService.disabled, prepareButton.disabled, reviewButton.disabled, closeButton.disabled, runtimeResetButton.disabled], [false, false, true, true, true]);
handlers.click({ target: { closest: (selector) => selector === '[data-hara-runtime-prepare]' ? prepareButton : null } });
assert.match(runtimeStatus.textContent, /This is not a request; nothing was sent or stored/);
location.hash = '#/citadels';
location.hash = '#/elixirs?view=scenario';
assert.match(runtimeStatus.textContent, /Synthetic-only demo ready/);
assert.deepEqual([runtimeService.disabled, prepareButton.disabled, reviewButton.disabled, closeButton.disabled, runtimeResetButton.disabled], [false, false, true, true, true]);

console.log('GO-6 smoke checks: PASS');
