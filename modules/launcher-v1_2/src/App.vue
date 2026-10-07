<script setup>
import { reactive, ref, computed, onMounted, onUnmounted } from 'vue';
import { createModuleStates } from './catalog.js';
import { createVerifier } from './verifier.js';
import { parseInWorker } from './worker-parser.js';

const modules = reactive(createModuleStates());
const verifier = createVerifier({ modules, parseJson: parseInWorker });
const clockTick = ref(0);
let tickTimer;
const labels = Object.freeze({
  unconfigured: 'Niet ingesteld', not_approved: 'Bestemming niet goedgekeurd',
  checking: 'Controleren…', impossible: 'Controle niet mogelijk',
  failed: 'Verificatie mislukt', expired: 'Verificatie verlopen',
  verified: 'Modulemetadata bevestigd'
});
const verifiedCount = computed(() => modules.filter(module => module.status === 'verified').length);
const globalStatusText = computed(() => verifiedCount.value === modules.length ? 'Alle modules: metadata bevestigd'
  : verifiedCount.value > 0 ? 'Gedeeltelijke verificatie' : 'Geen modules geverifieerd');
const globalStatusClass = computed(() => verifiedCount.value === modules.length ? 'ok' : verifiedCount.value ? 'warning' : 'critical');
function remaining(module) {
  void clockTick.value;
  return verifier.remainingSeconds(module);
}
function localTime(time) {
  return new Date(time).toLocaleTimeString('nl-NL');
}
function checkReturn() { verifier.suspend(); clockTick.value++; }
function onVisibility() { checkReturn(); }
function onPageShow(event) { if (event.persisted) checkReturn(); }

onMounted(() => {
  tickTimer = setInterval(() => { verifier.refreshAll(); clockTick.value++; }, 250);
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('focus', checkReturn);
  window.addEventListener('pagehide', checkReturn);
  window.addEventListener('pageshow', onPageShow);
  document.addEventListener('freeze', checkReturn);
});
onUnmounted(() => {
  clearInterval(tickTimer);
  document.removeEventListener('visibilitychange', onVisibility);
  window.removeEventListener('focus', checkReturn);
  window.removeEventListener('pagehide', checkReturn);
  window.removeEventListener('pageshow', onPageShow);
  document.removeEventListener('freeze', checkReturn);
  verifier.dispose();
});
</script>

<template>
  <div class="palaco-container">
    <header class="palaco-header">
      <div class="brand">
        <p class="eyebrow">HOOFDKANTOOR</p>
        <h1>PALACO</h1>
        <span class="subtitle">LAUNCHER // v1.2 HERSTELCANDIDATE</span>
      </div>
      <div class="system-status" role="status">
        <span class="status-dot" :class="globalStatusClass" aria-hidden="true"></span>
        {{ globalStatusText }}
      </div>
    </header>

    <main>
      <aside class="preview-note" aria-label="Previewstatus">
        <strong>PREVIEW — GEEN ACCEPTATIE / PRODUCTIE</strong>
        <p>Dit is de launcher. AETHER, BASTION en 5CRIPTIE zijn nog niet als werkende apps overgedragen.</p>
        <p>Agenda-uitvoering is geblokkeerd. Deze preview verleent geen toestemming om afspraken te wijzigen.</p>
      </aside>
      <div class="intro">
        <h2>Controleer je bestemming.</h2>
        <p>Vul een toegestane HTTPS-origin in. Open de module nadat de metadata is bevestigd.</p>
      </div>
      <div class="modules-grid">
        <article v-for="module in modules" :key="module.id" class="module-card"
          :class="module.status" :style="{ '--module-color': module.color }" :data-module="module.id">
          <div class="card-header">
            <div class="icon-box" aria-hidden="true">
              <svg v-if="module.id === 'aether'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>
              </svg>
              <svg v-else-if="module.id === 'bastion'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <path d="M4 21V5h4V2h8v3h4v16H4ZM8 21v-7h8v7M8 8h1m6 0h1"/>
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                <circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18M5 7h14M5 17h14"/>
              </svg>
            </div>
            <span class="status-badge" :class="module.status" role="status" data-status>{{ labels[module.status] }}</span>
          </div>
          <h2>{{ module.name }}</h2>
          <p class="description">{{ module.description }}</p>
          <div class="config-section">
            <label :for="`origin-${module.id}`">Toegestane HTTPS-origin</label>
            <input :id="`origin-${module.id}`" type="url" :value="module.inputUrl"
              :placeholder="module.placeholder" autocomplete="off" autocapitalize="off" spellcheck="false"
              :aria-invalid="!!module.error" :aria-describedby="`detail-${module.id}`"
              @input="verifier.changeInput(module, $event.target.value)" />
            <div class="config-actions">
              <button type="button" data-verify :disabled="!module.isValid || module.isVerifying" @click="verifier.verify(module)">
                {{ module.isVerifying ? 'Controleren…' : 'Opslaan & verifiëren' }}
              </button>
              <button v-if="module.isVerifying" type="button" class="cancel-btn" data-cancel @click="verifier.cancel(module)">Annuleren</button>
            </div>
            <div :id="`detail-${module.id}`" class="details" aria-live="polite">
              <p v-if="module.error" class="error-msg">{{ module.error }}</p>
              <div v-if="module.lastCheck" class="check-details">
                <span>Laatste check: {{ localTime(module.lastCheck.time) }}</span>
                <span v-if="module.lastCheck.result === 'success'" class="success-detail">ID bevestigd: {{ module.lastCheck.receivedId }}</span>
              </div>
            </div>
            <p v-if="module.status === 'verified'" class="expiry-timer" data-countdown>Vervalt over {{ remaining(module) }}s</p>
          </div>
          <button type="button" class="launch-btn" data-launch :disabled="module.status !== 'verified'" @click="verifier.open(module)">
            {{ module.status === 'verified' ? 'Open module' : 'Wacht op verificatie' }}
          </button>
        </article>
      </div>
    </main>

    <footer class="palaco-footer">
      <p>Metadata bevestigd betekent: de ingestelde origin leverde JSON met de verwachte appId en een statusveld.</p>
      <p>Dit bevestigt geen authenticatie, autorisatie of gegarandeerde veiligheid.</p>
      <p>Een bevestiging vervalt na maximaal 60 seconden. Bij terugkeer naar deze pagina verifieer je opnieuw.</p>
    </footer>
  </div>
</template>
