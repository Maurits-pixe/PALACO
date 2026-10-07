/* GO-6 public shell. The frontend has no authority and never turns a mark into proof. */
const nav = [
  ['citadels', 'Citadels'], ['elixirs', 'Elixirs'], ['proof', 'Proof'],
  ['industrie', 'Industrie'], ['governance', 'Governance'], ['evolution', 'Evolution']
];
const la = {
  id: 'LA-001', name: 'Locus Amoenus', role: 'Reference Citadel', status: 'DRAFT',
  verification: 'UNVERIFIED', version: 'PVD-001 v1.0',
  spaces: ['Observatory', 'Commons', 'Elixirs', 'H∆R∆M'],
  towers: ['LOGO — Access & Identity', 'HARBOR — Traffic & Transit', 'QUAY — Storage & Provenance', 'KEEP — Defense & Oversight']
};
const esc = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const link = (route, label) => `<a class="button" href="#/${route}">${label}</a>`;
const architecture = () => `<ol class="architecture" aria-label="Citadel architecture journey">${['Perimeter','Crown','Four Towers','Core'].map((item, index) => `<li class="journey"><span class="eyebrow">0${index + 1}</span><strong>${item}</strong></li>`).join('')}</ol>`;
const header = (eyebrow, title, text) => `<section class="intro"><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p>${text}</p></section>`;
const card = (title, text, route) => `<article class="card"><p class="eyebrow">${title}</p><p>${text}</p>${route ? link(route, 'Explore') : ''}</article>`;
const page = (content) => content;

function home() {
  return page(`<section class="hero"><div class="hero-copy"><p class="eyebrow">PALACO.NL · PVD-001 · v1.0</p><p class="hero-kicker">A clearer way to build what comes next.</p><h1>Trust starts<br>with clarity.</h1><p class="hero-lede">Constitutional infrastructure for bounded digital environments — with identity, provenance and status in view.</p><div class="hero-actions"><a class="button button-primary" href="studio.html">Open PALACO Studio <span aria-hidden="true">↗</span></a><a class="text-link" href="#/citadels">Explore the architecture <span aria-hidden="true">↓</span></a></div><p class="hero-note"><span class="status-dot" aria-hidden="true"></span> PUBLIC BASELINE <span>·</span> DRAFT / UNVERIFIED</p></div><div class="hero-art" aria-hidden="true"><div class="art-orbit orbit-one"></div><div class="art-orbit orbit-two"></div><div class="art-core"><span>PALACO</span><strong>△</strong><small>BOUNDED BY DESIGN</small></div><div class="art-label art-label-top">IDENTITY <span>01</span></div><div class="art-label art-label-side">PROVENANCE <span>02</span></div><div class="art-caption">A framework for what matters.</div></div></section>
  <section class="section"><div class="section-heading"><p class="eyebrow">The PALACO approach</p><h2>Make the important things visible before anyone steps inside.</h2><p class="section-intro">Every environment has a purpose, a boundary and a story. PALACO brings them into focus.</p></div><div class="grid">${card('Citadels','Places and environments with identity, function and provenance.','citadels')}${card('Proof','Identity, provenance and status made inspectable.','proof')}${card('Evolution','Systems, experiments and change kept visible.','evolution')}</div></section>
  <section class="section dark"><p class="eyebrow">Reference Citadel · LA-001</p><h2>Locus Amoenus</h2><p>A living reference environment for PALACO architecture. Enter from the perimeter and inspect each layer at your own pace.</p>${architecture()}${link('citadels/la-001','Enter L.A.')}</section>
  <section class="section"><div class="grid">${card('Elixirs','Curated experiences with origin, status and provenance.','elixirs')}${card('H∆R∆M','A human interface for orientation, context and action.','haram')}${card('Industrie','The practical layer for identity, infrastructure, commerce and research.','industrie')}</div></section>`);
}

function citadels(route) {
  if (route === 'citadels/la-001') return page(`${header('PALACO · CITADEL · LA-001', 'Locus Amoenus', 'Reference Citadel — a bounded PALACO environment with its own identity, function and provenance.')}
    <section class="section"><span class="badge">${la.status}</span> <span class="badge">${la.verification}</span><dl><dt>Citadel ID</dt><dd>${la.id}</dd><dt>Version</dt><dd>${la.version}</dd><dt>Visibility</dt><dd>PUBLIC</dd></dl>${architecture()}</section>
    <section class="section"><p class="eyebrow">Internal spaces</p><div class="grid">${la.spaces.map((x) => card(x, 'A named space in the L.A. reference architecture.')).join('')}</div></section>
    <section class="section"><p class="eyebrow">Four towers</p><div class="grid">${la.towers.map((x) => card(x, 'A constitutional tower. Its label does not itself confer authority.')).join('')}</div></section>
    <section class="section"><p class="eyebrow">Proof boundary</p><h2>Displayed identity remains separate from verified identity.</h2><p>L.A. is currently a public design and content baseline. No live issuer, Watermerk, Seal or verification provider is connected in this release.</p>${link('proof','Inspect Proof')}</section>`);
  return page(`${header('PALACO · CITADELS', 'Citadels', 'Bounded environments within the PALACO architecture.')}
    <section class="section"><div class="grid">${card('LA-001 · Reference Citadel','LOCUS AMOENUS — the first public reference environment.','citadels/la-001')}</div></section>`);
}

function proof() {
  return page(`${header('PALACO · PROMA', 'Proof', 'Identity, provenance and status made inspectable.')}
    <section class="section"><div class="grid">${card('Identity','Who or what is this?','identity')}${card('Provenance','Where did it come from?','proof/provenance')}${card('Validity','What is its current state?','proof/verify')}</div></section>
    <section class="section"><p class="eyebrow">Verify</p><h2>Search identity, Citadel, Watermerk or provenance reference.</h2><form data-verification><label for="reference">Reference</label><input id="reference" name="reference" autocomplete="off" placeholder="LA-001, identity or Watermerk"><button class="button" type="submit">Verify</button></form><output id="verification-result" aria-live="polite"></output></section>`);
}

function detail(route) {
  const map = {
    'elixirs': ['Elixirs','Curated experiences within the PALACO ecosystem.','No public Elixir records are registered in this baseline. Every future item will expose origin, Citadel, Watermerk, provenance and status.'],
    'industrie': ['Industrie','Where the architecture becomes useful.','Identity · Provenance · Infrastructure · Commerce · Research · Implementation.'],
    'governance': ['Governance','Authority should be attributable, bounded, reviewable and revocable.','Roles, authority, boundaries, review, revocation and history are public concepts. A displayed role is not an execution authorization.'],
    'evolution': ['Evolution','The public change record of PALACO.','CURRENT · PREVIOUS · PROPOSALS · EXPERIMENTS · ARCHIVE. Change is visible and versioned.'],
    'identity': ['Identity','Carry your PALACO identity with you.','Public identity surfaces expose only appropriate information. Identity presentation never implies authority.'],
    'haram': ['H∆R∆M','Living interface between the human and the constitutional architecture.','Orient · Understand · Navigate · Verify · Act — always in context of Citadel, status and version.'],
    'stewardship': ['Stewardship','Responsibility without implied ownership.','Steward → Role → Authority scope → Review → Revocation.'],
    'about': ['About PALACO','The threshold into a constitutional architecture.','PALACO is a framework for bounded environments in which identity, participation, provenance and evidence remain visible and understandable.'],
    'constitution': ['Constitution','The public rules underlying the architecture.','Purpose · Identity · Boundaries · Authority · Provenance · Status · Review · Revocation · Evolution.']
  };
  const [title, subtitle, body] = map[route] || ['The path is not found','The requested architectural location does not currently exist.','Return to the PALACO threshold.'];
  return page(`${header(`PALACO · ${title.toUpperCase()}`, title, subtitle)}<section class="section"><h2>${body}</h2><p>Current public status: <span class="badge">DRAFT</span> <span class="badge">UNVERIFIED</span></p>${link('','Return to PALACO')}</section>`);
}

function syncNavigation(routeName) {
  const section = routeName.split('/')[0];
  document.querySelectorAll('header nav a').forEach((anchor) => {
    const target = anchor.getAttribute('href').replace(/^#\/?/, '').replace(/\/$/, '');
    if (section && target === section) anchor.setAttribute('aria-current', 'page');
    else anchor.removeAttribute('aria-current');
  });
}

function route() {
  const raw = location.hash.replace(/^#\/?/, '').replace(/\/$/, '') || '';
  const main = document.querySelector('#main');
  if (raw === '' || raw === 'enter') main.innerHTML = home();
  else if (raw === 'citadels' || raw === 'citadels/la-001') main.innerHTML = citadels(raw);
  else if (raw === 'proof' || raw === 'proof/verify') main.innerHTML = proof();
  else if (raw === 'proof/provenance') main.innerHTML = page(`${header('PALACO · PROOF', 'Provenance', 'A chain that can be inspected step by step.')}<section class="section"><ol class="architecture">${['Origin','Issuer','Citadel','Watermerk','Seal','Provenance','Validity'].map((x, i) => `<li><span class="eyebrow">0${i + 1}</span><strong>${x}</strong></li>`).join('')}</ol><p class="badge">UNVERIFIED</p><p>No authoritative chain is connected in this baseline.</p></section>`);
  else if (raw === 'proof/watermerk') main.innerHTML = page(`${header('PALACO · PROOF', 'Watermerk', 'An identity-bearing authenticity layer.')}<section class="section"><p class="badge">UNVERIFIED</p><p>No Watermerk record is available to verify in this baseline.</p></section>`);
  else main.innerHTML = detail(raw);
  document.title = raw ? `${raw.split('/').pop().toUpperCase()} — PALACO` : 'PALACO — Constitutional infrastructure';
  syncNavigation(raw);
  main.focus({preventScroll: true});
  window.scrollTo(0, 0);
}

window.addEventListener('hashchange', route);
document.addEventListener('submit', (event) => {
  if (!event.target.matches('[data-verification]')) return;
  event.preventDefault();
  const input = event.target.querySelector('input');
  const reference = input.value.trim();
  const output = document.querySelector('#verification-result');
  if (!reference) { input.setCustomValidity('Enter an identity, Citadel-ID or evidence reference.'); input.reportValidity(); return; }
  input.setCustomValidity('');
  output.textContent = `UNVERIFIED — Evidence could not be established for “${reference}”. No authoritative verification service is connected. No access or authority is granted.`;
});
route();
