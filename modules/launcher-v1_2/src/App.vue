<script setup>
import { reactive, ref, computed, onMounted, onUnmounted } from 'vue';
import { CATALOG, createModuleStates } from './catalog.js';
import { createVerifier } from './verifier.js';
import { parseInWorker } from './worker-parser.js';

const modules = reactive(createModuleStates());
const moduleOrigins = Object.fromEntries(CATALOG.map(({ id, origins }) => [id, origins]));
const verifier = createVerifier({ modules, parseJson: parseInWorker });
const clockTick = ref(0);
const launcherOrigin = window.location.origin;
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
function focusOrigin(event) {
  event.currentTarget.form.querySelector('input')?.focus();
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
    <a class="skip-link" href="#launcher-content">Ga naar hoofdinhoud</a>
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

    <main id="launcher-content" tabindex="-1">
      <aside class="preview-note" aria-label="Previewstatus">
        <strong>PREVIEW — GEEN ACCEPTATIE / PRODUCTIE</strong>
        <p>Dit is de launcher. AETHER, BASTION en 5CRIPTIE zijn nog niet als werkende apps overgedragen.</p>
        <p>Agenda-uitvoering is geblokkeerd. Deze preview verleent geen toestemming om afspraken te wijzigen.</p>
        <p>Launcher-origin: <code data-launcher-origin>{{ launcherOrigin }}</code></p>
        <p>Voor module-CORS gebruik je deze exacte origin. Dit is geen bewijs van domeineigendom of autorisatie.</p>
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
          <h2 :id="`module-${module.id}`">{{ module.name }}</h2>
          <p class="description">{{ module.description }}</p>
          <form class="config-section" novalidate :aria-labelledby="`module-${module.id}`"
            @submit.prevent="module.isValid && !module.isVerifying && verifier.verify(module)">
            <label :for="`origin-${module.id}`">Toegestane HTTPS-origin voor {{ module.name }}</label>
            <input :id="`origin-${module.id}`" type="url" :value="module.inputUrl"
              :placeholder="module.placeholder" autocomplete="off" autocapitalize="off" spellcheck="false"
              :aria-invalid="!!module.error" :aria-describedby="`detail-${module.id}`"
              @input="verifier.changeInput(module, $event.target.value)" />
            <details class="origin-choices">
              <summary>Ingestelde bestemmingen voor {{ module.name }}</summary>
              <p>Catalogusconfiguratie, geen bewijs dat de app werkt. Kiezen vult alleen het veld in; verifieer daarna zelf.</p>
              <ul>
                <li v-for="origin in moduleOrigins[module.id]" :key="origin">
                  <button type="button" data-origin-choice @click="verifier.changeInput(module, origin)">{{ origin }}</button>
                </li>
              </ul>
            </details>
            <div class="config-actions">
              <button type="submit" data-verify :disabled="!module.isValid || module.isVerifying"
                :aria-label="`${module.isVerifying ? 'Controleren…' : 'Opslaan & verifiëren'} ${module.name}`">
                {{ module.isVerifying ? 'Controleren…' : 'Opslaan & verifiëren' }}
              </button>
              <button v-if="module.isVerifying" type="button" class="cancel-btn" data-cancel
                :aria-label="`Annuleren ${module.name}`" @click="verifier.cancel(module); focusOrigin($event)">Annuleren</button>
              <button type="button" data-clear :disabled="!module.inputUrl"
                :aria-label="`Wissen ${module.name}`" @click="verifier.changeInput(module, ''); focusOrigin($event)">Wissen</button>
            </div>
            <div :id="`detail-${module.id}`" class="details" aria-live="polite">
              <p v-if="module.error" class="error-msg">{{ module.error }}</p>
              <p v-if="module.error && module.errorCode" data-error-code>Foutcode: <code>{{ module.errorCode }}</code></p>
              <div v-if="module.lastCheck" class="check-details">
                <span>Laatste check: {{ localTime(module.lastCheck.time) }}</span>
                <span v-if="module.lastCheck.result === 'success'" class="success-detail">ID bevestigd: {{ module.lastCheck.receivedId }}</span>
                <template v-if="module.status === 'verified'">
                  <span data-checked-origin>Gecontroleerde origin: <code>{{ module.lastCheck.origin }}</code></span>
                  <span data-reported-status>Gemelde modulestatus (onvertrouwde tekst): <code>{{ JSON.stringify(module.lastCheck.receivedStatus) }}</code></span>
                  <span>Deze status is geen bewijs van bereikbaarheid van functies, veiligheid of autorisatie.</span>
                </template>
              </div>
            </div>
            <p v-if="module.status === 'verified'" class="expiry-timer" data-countdown>Vervalt over {{ remaining(module) }}s</p>
          </form>
          <button type="button" class="launch-btn" data-launch :disabled="module.status !== 'verified'"
            :aria-label="`${module.status === 'verified' ? 'Open module' : 'Wacht op verificatie'} ${module.name}`" @click="verifier.open(module)">
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
