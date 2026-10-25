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
  <section class="section"><div class="grid">${card('Elixirs','Curated experiences with origin, status and provenance.','elixirs')}${card('H∆R∆M','A human interface for orientation, context, and provenance inspection.','haram')}${card('Industrie','The practical layer for identity, infrastructure, commerce and research.','industrie')}</div></section>`);
}

function citadels(route) {
  if (route === 'citadels/la-001') return page(`${header('PALACO · CITADEL · LA-001', 'Locus Amoenus', 'Reference Citadel — a bounded PALACO environment with its own identity, function and provenance.')}
    <section class="section"><span class="badge">${la.status}</span> <span class="badge">${la.verification}</span><dl><dt>Citadel ID</dt><dd>${la.id}</dd><dt>Version</dt><dd>${la.version}</dd><dt>Visibility</dt><dd>PUBLIC</dd></dl>${architecture()}</section>
    <section class="section"><p class="eyebrow">Internal spaces</p><div class="grid">${la.spaces.map((x) => card(x, 'A named space in the L.A. reference architecture.')).join('')}</div></section>
    <section class="section"><p class="eyebrow">Four towers</p><div class="grid">${la.towers.map((x) => card(x, 'A constitutional tower. Its label does not itself confer authority.')).join('')}</div></section>
    <section class="section"><p class="eyebrow">Household layer · proposal</p><h2>HARA could help each Citadel coordinate shared services.</h2><p>Possible functions include service discovery, request tracking, and care or maintenance coordination. This is a design proposal, not a live LA-001 service or established HARA capability.</p><p>Each Citadel would require its own service catalogue, data boundary, consent and access policy, accountable operators, and revocation path. A request would not authorize or execute an action. Cross-Citadel sharing would require an explicit contract and review.</p><p>HARA is not being equated with H∆R∆M; identity and authority remain unestablished.</p><span class="badge">PROPOSED</span> <span class="badge">NOT IMPLEMENTED</span></section>
    <section class="section"><p class="eyebrow">Proof boundary</p><h2>Displayed identity remains separate from verified identity.</h2><p>L.A. is currently a public design and content baseline. No live issuer, Watermerk, Seal or verification provider is connected in this release.</p>${link('proof','Inspect Proof')}</section>`);
  return page(`${header('PALACO · CITADELS', 'Citadels', 'Bounded environments within the PALACO architecture.')}
    <section class="section"><div class="grid">${card('LA-001 · Reference Citadel','LOCUS AMOENUS — the first public reference environment.','citadels/la-001')}</div></section>`);
}

function proof() {
  return page(`${header('PALACO · PROMA', 'Proof', 'Identity, provenance and status made inspectable.')}
    <section class="section"><div class="grid">${card('Identity','Who or what is this?','identity')}${card('Provenance','Where did it come from?','proof/provenance')}${card('Validity','What is its current state?','proof/verify')}</div></section>
    <section class="section"><p class="eyebrow">Verify</p><h2>Search identity, Citadel, Watermerk or provenance reference.</h2><form data-verification><label for="reference">Reference</label><input id="reference" name="reference" autocomplete="off" placeholder="LA-001, identity or Watermerk"><button class="button" type="submit">Verify</button></form><output id="verification-result" aria-live="polite"></output></section>`);
}

function elixirs() {
  return page(`${header('PALACO · ELIXERS', 'Elixirs', 'Curated experiences with origin, status, and provenance.')}
    <section class="section"><p>No public Elixir records are registered in this baseline. The HARA widget below is a proposed layout preview, not a registered or connected Elixir.</p>
      <article class="hara-widget" aria-labelledby="hara-widget-title">
        <header class="hara-widget__header"><div><p class="eyebrow">HOUSEHOLD · WIDGET CONCEPT</p><h2 id="hara-widget-title">HARA desk</h2></div><span class="badge">PROPOSED</span></header>
        <div class="hara-widget__body">
          <section class="hara-widget__main" aria-label="Household overview preview">
            <p class="hara-widget__welcome">A clearer view of this Citadel’s shared services.</p>
            <div class="hara-widget__metrics">
              <div><span>Services</span><strong>Not connected</strong></div>
              <div><span>Requests</span><strong>Not connected</strong></div>
              <div><span>Updates</span><strong>Not connected</strong></div>
            </div>
            <h3>Household services</h3>
            <ul class="hara-widget__services">
              <li><span class="hara-widget__icon" aria-hidden="true">＋</span><span><strong>Care &amp; wellbeing</strong><small>Discover locally defined support</small></span><span class="badge">PROPOSED</span></li>
              <li><span class="hara-widget__icon" aria-hidden="true">⌂</span><span><strong>Maintenance</strong><small>Find the Citadel’s service contacts</small></span><span class="badge">PROPOSED</span></li>
              <li><span class="hara-widget__icon" aria-hidden="true">◇</span><span><strong>Citadel guide</strong><small>Understand spaces and shared resources</small></span><span class="badge">PROPOSED</span></li>
            </ul>
            <details class="hara-widget__flow">
              <summary>How a future request might be handled</summary>
              <ol>
                <li><strong>Describe</strong><span>A resident chooses a locally available service and provides only the information it requires.</span></li>
                <li><strong>Review</strong><span>The responsible service reviews the request under its published policy and consent rules.</span></li>
                <li><strong>Decide</strong><span>An accountable operator or authorized service records approval, refusal, or a request for clarification.</span></li>
                <li><strong>Update</strong><span>The resident can inspect the recorded status and applicable retention or appeal information.</span></li>
              </ol>
              <p>Illustrative workflow only. No request can be created from this preview.</p>
            </details>
          </section>
          <aside class="hara-widget__boundary"><p class="eyebrow">STATUS &amp; BOUNDARY</p><span class="badge">DRAFT / UNVERIFIED</span><p>This is a static layout concept. It reads no household data and submits no requests.</p><p>A request would not grant permission or execute an action. Each Citadel would define its own services, data, consent, access policy, and accountable operator.</p><p>HARA is not H∆R∆M. Identity, authority, and runtime execution are not established.</p></aside>
        </div>
        <footer class="hara-widget__footer"><span>LA-001 · Reference layout only</span><span>NO LIVE SERVICE</span></footer>
      </article>
    </section>`);
}

function haram() {
  return page(`${header('PALACO · HUMAN INTERFACE', 'H∆R∆M', 'A presentation and interaction layer for the L.A. ecosystem.')}
    <section class="section"><p class="eyebrow">Role and scope</p><h2>Help people explore, understand, and inspect.</h2><ul><li>Explore the Citadel and orient within its spaces.</li><li>Explain architectural information.</li><li>Support provenance inspection and evidence visibility.</li><li>Facilitate interaction with ELIXERS.</li></ul><dl><dt>Capability</dt><dd>PRESENT — present, explain, guide, and make information accessible within applicable boundaries.</dd><dt>Authority</dt><dd>NOT ESTABLISHED</dd><dt>Runtime execution</dt><dd>NOT ESTABLISHED</dd><dt>Issuance and governance</dt><dd>NOT ESTABLISHED</dd></dl></section>
    <section class="section"><p class="eyebrow">Explore</p><h2>Choose an architecture view.</h2><p>These links navigate public information only; they do not verify identity, grant access, or authorize an action.</p>${link('citadels/la-001','Explore Locus Amoenus')}${link('proof/provenance','Inspect provenance overview')}${link('elixirs','View ELIXERS')}</section>
    <section class="section"><p class="eyebrow">Boundary</p><h2>Presentation is not authority.</h2><p>Interface prominence, naming, or interaction does not grant authorization, execution, issuance, governance, signing, or kernel access. PRESENT does not imply those capabilities.</p></section>
    <section class="section"><p class="eyebrow">Identity and relationship review</p><h2>Related names remain separate unless explicitly established.</h2><p>HARA, HARAM, H∆R∆M, and HARA-LAB-001 / H∆R∆ are not automatically equivalent. The proposed H∆R∆M-is-Matriarch-of-H∆R∆ relationship is NOT_ESTABLISHED. No identity merge or inherited authority, capability, or namespace is assumed.</p></section>
    <section class="section"><p class="eyebrow">Current public status</p><span class="badge">DRAFT</span> <span class="badge">UNVERIFIED</span><p>This page describes the public design baseline, not a verified runtime or production activation. Human review is required; production activation is not allowed by this status.</p></section>`);
}

function detail(route) {
  const map = {
    'elixirs': ['Elixirs','Curated experiences within the PALACO ecosystem.','No public Elixir records are registered in this baseline. Every future item will expose origin, Citadel, Watermerk, provenance and status.'],
    'industrie': ['Industrie','Where the architecture becomes useful.','Identity · Provenance · Infrastructure · Commerce · Research · Implementation.'],
    'governance': ['Governance','Authority should be attributable, bounded, reviewable and revocable.','Roles, authority, boundaries, review, revocation and history are public concepts. A displayed role is not an execution authorization.'],
    'evolution': ['Evolution','The public change record of PALACO.','CURRENT · PREVIOUS · PROPOSALS · EXPERIMENTS · ARCHIVE. Change is visible and versioned.'],
    'identity': ['Identity','Carry your PALACO identity with you.','Public identity surfaces expose only appropriate information. Identity presentation never implies authority.'],
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
  else if (raw === 'elixirs') main.innerHTML = elixirs();
  else if (raw === 'haram') main.innerHTML = haram();
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
