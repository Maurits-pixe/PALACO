<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import manifest from './manifest.json';
import { startAmbientAnimation } from './animation.js';
import { applyFixtureEvent, normalizeWorldManifest, validateWorldManifest } from './world.js';

const validation = validateWorldManifest(manifest);
const normalizedManifest = normalizeWorldManifest(manifest);
const referenceImage = '/assets/world-eva-001-reference.png';
const readModel = ref({
  sequence: 41,
  validationState: 'UNKNOWN',
  traceRef: 'synthetic:eva:41',
  transportState: 'LOCAL_FIXTURE',
  issues: [],
  events: [{
    sequence: 41,
    eventType: 'REFERENCE_LOADED',
    region: 'PROOF',
    validationState: 'UNKNOWN',
    traceRef: 'synthetic:eva:41',
  }],
});

const regions = manifest.structure.regions;
const landmarks = manifest.structure.landmarks;
const nextEvent = {
  sequence: 42,
  eventType: 'RIO_SIGNAL_RECEIVED',
  region: 'PROOF',
  validationState: 'UNKNOWN',
  traceRef: 'synthetic:eva:42',
};
const eventAvailable = computed(() => readModel.value.sequence < nextEvent.sequence);
const eventPulse = ref(false);
const canvas = ref(null);
let stopAnimation = () => {};
let pulseTimer;

function replayFixtureEvent() {
  readModel.value = applyFixtureEvent(readModel.value, nextEvent);
  eventPulse.value = true;
  clearTimeout(pulseTimer);
  pulseTimer = setTimeout(() => { eventPulse.value = false; }, 900);
}

onMounted(() => {
  if (canvas.value) stopAnimation = startAmbientAnimation(canvas.value);
});

onUnmounted(() => {
  stopAnimation();
  clearTimeout(pulseTimer);
});
</script>

<template>
  <div class="page-shell">
    <a class="skip-link" href="#main-content">Ga naar inhoud</a>
    <header class="topbar">
      <a class="wordmark" href="#main-content" aria-label="PALACO EVA preview">PALACO <span>WORLD</span></a>
      <div class="topbar-state">
        <span class="state-light" aria-hidden="true"></span>
        <span>LOKALE ONTWERP-PREVIEW</span>
      </div>
    </header>

    <main id="main-content">
      <section class="notice" role="note" aria-label="Previewgrenzen">
        <strong>SYNTHETISCHE FIXTURE — READ-ONLY</strong>
        <span>Geen World API, live stream, opslag, activatie of externe effecten.</span>
      </section>

      <section class="intro">
        <div>
          <p class="eyebrow">OR6IT / WORLD-EVA-001</p>
          <h1>EVA <span>is een belofte.</span></h1>
          <p class="lede">Een read-only ontwerp-preview voor de eerste PALACO World referentie.</p>
        </div>
        <dl class="lifecycle-card">
          <div><dt>Ontwerpstatus</dt><dd>{{ manifest.lifecycle.design_state }}</dd></div>
          <div><dt>Uitvoering</dt><dd class="blocked">{{ manifest.lifecycle.execution_state }}</dd></div>
          <div><dt>Constitutionele status</dt><dd class="unknown">UNKNOWN</dd></div>
        </dl>
      </section>

      <section class="scene" :class="{ 'event-pulse': eventPulse }" aria-labelledby="scene-title">
        <h2 id="scene-title" class="visually-hidden">Statische EVA-ontwerpreferentie met decoratieve beweging</h2>
        <img
          class="reference-image"
          :src="referenceImage"
          alt="Door de gebruiker aangeleverde conceptafbeelding voor WORLD-EVA-001: EVA, met de centrale toren, ringen, vier regio's en zeven landmarks."
          width="1312"
          height="1199"
        />
        <div class="scene-shade" aria-hidden="true"></div>
        <svg class="scene-diagram" viewBox="0 0 1000 560" role="img" aria-labelledby="diagram-title diagram-description">
          <title id="diagram-title">Decoratieve EVA-structuur</title>
          <desc id="diagram-description">Horizon, Gate, Ring en Core als visuele ontwerpmarkeringen; niet technisch of constitutioneel bewijs.</desc>
          <g class="ring-system">
            <ellipse cx="500" cy="315" rx="235" ry="76" />
            <ellipse cx="500" cy="315" rx="152" ry="49" />
          </g>
          <path class="core-axis" d="M500 78V414" />
          <circle class="core-mark" cx="500" cy="315" r="13" />
          <circle class="horizon-mark" cx="500" cy="130" r="4" />
        </svg>
        <canvas ref="canvas" class="ambient-canvas" aria-hidden="true"></canvas>
        <div class="scene-caption">
          <span>CONCEPT DESIGN REFERENCE</span>
          <span>Beweging is decoratief; status blijft expliciet.</span>
        </div>
      </section>

      <section class="identity-grid" aria-label="World-identiteit">
        <article class="info-card">
          <p class="eyebrow">WORLD IDENTITEIT</p>
          <h2>{{ manifest.world.name }}</h2>
          <dl>
            <div><dt>World ID</dt><dd>{{ manifest.world.id }}</dd></div>
            <div><dt>Klasse</dt><dd>{{ manifest.world.class }}</dd></div>
            <div><dt>Ontwikkel-engine</dt><dd>OR6IT — NON_AUTHORITATIVE</dd></div>
            <div><dt>Design language</dt><dd>{{ manifest.world.design_language }}</dd></div>
            <div><dt>Communicatie</dt><dd>{{ manifest.world.communication_layer }} — referentie</dd></div>
          </dl>
        </article>
        <article class="info-card">
          <p class="eyebrow">CITADEL REFERENTIES</p>
          <h2>{{ manifest.citadel.binding_id }}</h2>
          <dl>
            <div><dt>Constitutionele referentie</dt><dd>{{ manifest.citadel.constitutional_reference }}</dd></div>
            <div><dt>Manifestcontrole</dt><dd :class="validation.state === 'STRUCTURALLY_VALID' ? 'positive' : 'unknown'">{{ validation.state }}</dd></div>
            <div><dt>Evidence</dt><dd>{{ manifest.provenance.evidence_state }}</dd></div>
            <div><dt>Provenance</dt><dd>{{ manifest.provenance.validation_state }}</dd></div>
            <div><dt>Bronreferentie</dt><dd><code>{{ manifest.visual_reference.path }}</code></dd></div>
          </dl>
        </article>
      </section>

      <section class="structure-section" aria-labelledby="structure-title">
        <div class="section-heading">
          <div>
            <p class="eyebrow">READ MODEL / {{ manifest.schema_version }}</p>
            <h2 id="structure-title">Van Horizon naar Core</h2>
          </div>
          <p>Vaste fixturevolgorde; geen operationele route.</p>
        </div>
        <ol class="structure-flow">
          <li v-for="(layer, index) in manifest.structure.sequence" :key="layer">
            <span class="flow-index">0{{ index + 1 }}</span>
            <span>{{ layer.replaceAll('_', ' ') }}</span>
          </li>
        </ol>
      </section>

      <section class="detail-grid">
        <article class="panel" aria-labelledby="regions-title">
          <div class="panel-heading">
            <div><p class="eyebrow">FOUR REGIONS</p><h2 id="regions-title">Vier regio's</h2></div>
            <span class="quiet-badge">FIXTURE</span>
          </div>
          <div class="region-list">
            <article v-for="(region, index) in regions" :key="region.id" class="region-card">
              <span class="region-number">0{{ index + 1 }}</span>
              <div><h3>{{ region.label }}</h3><p>{{ region.purpose }}</p></div>
              <span class="region-state">{{ region.verification_state }}</span>
            </article>
          </div>
        </article>

        <article class="panel" aria-labelledby="landmarks-title">
          <div class="panel-heading">
            <div><p class="eyebrow">WORLD MAP / REFERENCES</p><h2 id="landmarks-title">Landmarks</h2></div>
            <span class="quiet-badge">{{ landmarks.length }} FIXTURES</span>
          </div>
          <ol class="landmark-list">
            <li v-for="landmark in landmarks" :key="landmark.id">
              <span class="landmark-node" aria-hidden="true"></span>
              <div><h3>{{ landmark.label }}</h3><p>{{ landmark.meaning }}</p></div>
            </li>
          </ol>
        </article>
      </section>

      <section class="event-section panel" aria-labelledby="events-title">
        <div class="panel-heading">
          <div><p class="eyebrow">WORLD CLOCK / SYNTHETIC ONLY</p><h2 id="events-title">Event- en traceweergave</h2></div>
          <span class="sequence-badge">SEQUENCE {{ readModel.sequence }}</span>
        </div>
        <div class="event-toolbar">
          <p>Data-clockstatus: <strong>{{ readModel.transportState }}</strong> · Validatiestatus: <strong>{{ readModel.validationState }}</strong></p>
          <button type="button" class="fixture-button" :disabled="!eventAvailable" @click="replayFixtureEvent">
            {{ eventAvailable ? 'Toon volgend fixture-event' : 'Fixture-event getoond' }}
          </button>
        </div>
        <p class="event-disclaimer">Deze knop speelt uitsluitend een ingebouwd synthetisch event af. Er wordt geen verzoek verzonden of World-state gewijzigd.</p>
        <ol class="event-list" aria-live="polite">
          <li v-for="event in [...readModel.events].reverse()" :key="event.sequence">
            <span class="event-sequence">{{ event.sequence }}</span>
            <div><strong>{{ event.eventType }}</strong><span>{{ event.region }} · {{ event.validationState }}</span></div>
            <code>{{ event.traceRef }}</code>
          </li>
        </ol>
        <p v-if="readModel.issues.length" class="validation-issues" role="status">{{ readModel.issues.join(' ') }}</p>
      </section>

      <section class="boundary-strip" aria-label="Constitutionele grenzen">
        <p><span>DESIGN</span><b>≠</b><span>VALIDATIE</span><b>≠</b><span>AUTHORITY</span><b>≠</b><span>EXECUTION</span></p>
        <small>Een geldige manifeststructuur verleent geen vertrouwen, toestemming of activatie.</small>
      </section>

      <details class="manifest-details">
        <summary>Toon genormaliseerde fixture ({{ normalizedManifest.length }} tekens)</summary>
        <pre><code>{{ normalizedManifest }}</code></pre>
      </details>
    </main>

    <footer>
      <span>PALACO / OR6IT / WORLD-EVA-001</span>
      <span>Preview only · DESIGN_DRAFT · NOT_AUTHORIZED</span>
    </footer>
  </div>
</template>
