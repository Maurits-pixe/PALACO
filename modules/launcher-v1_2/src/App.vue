<script setup>
import { reactive, ref, computed, onMounted, onUnmounted } from 'vue';
import { createModuleStates } from './catalog.js';
import { createVerifier } from './verifier.js';
import { parseInWorker } from './worker-parser.js';

const modules = reactive(createModuleStates());
const verifier = createVerifier({ modules, parseJson: parseInWorker });
const clockTick = ref(0);
const globalLogs = ref([]);
const openedLinks = ref([]);
const panicLocked = ref(false);
let tickTimer;
let nextLogId = 0;
const labels = Object.freeze({
  unconfigured: 'Niet ingesteld', not_approved: 'Bestemming niet goedgekeurd',
  checking: 'Controleren…', impossible: 'Controle niet mogelijk',
  failed: 'Verificatie mislukt', expired: 'Verificatie verlopen',
  verified: 'Modulemetadata bevestigd'
});
const verifiedCount = computed(() => modules.filter(module => module.status === 'verified').length);
const sessionValid = computed(() => verifiedCount.value > 0);
const launchedModuleCount = computed(() => new Set(openedLinks.value.map(link => link.moduleId)).size);
const sessionRemaining = computed(() => {
  void clockTick.value;
  return Math.max(0, ...modules.map(module => verifier.remainingSeconds(module)));
});
const globalStatusText = computed(() => verifiedCount.value === modules.length ? 'Alle modulemetadata bevestigd'
  : verifiedCount.value > 0 ? 'Gedeeltelijke metadata-controle' : 'Geen actuele verificatie');
const globalStatusClass = computed(() => verifiedCount.value === modules.length ? 'ok' : verifiedCount.value ? 'warning' : 'critical');
function remaining(module) {
  void clockTick.value;
  return verifier.remainingSeconds(module);
}
function localTime(time) {
  return time == null ? '--:--:--' : new Date(time).toLocaleTimeString('nl-NL');
}
function addLog(source, message, type = 'info') {
  globalLogs.value.unshift({ id: ++nextLogId, timestamp: Date.now(), source, message, type });
  if (globalLogs.value.length > 50) globalLogs.value.length = 50;
}
async function verifyModule(module) {
  if (panicLocked.value) return;
  module.checkLatencyMs = null;
  module.tlsStatus = 'unknown';
  const started = performance.now();
  const verification = verifier.verify(module);
  const checkId = module.currentCheckId;
  await verification;
  if (module.currentCheckId !== checkId || !module.lastCheck) return;
  module.checkLatencyMs = Math.round(performance.now() - started);
  if (module.lastCheck.result === 'success') {
    module.tlsStatus = 'accepted';
    addLog(module.name, `Metadata bevestigd (${module.checkLatencyMs} ms).`, 'success');
  } else {
    addLog(module.name, `Metadata niet bevestigd: ${module.lastCheck.reason}`, 'error');
  }
}
function openModule(module) {
  if (panicLocked.value || !verifier.open(module)) return;
  openedLinks.value.unshift({ moduleId: module.id, name: module.name, timestamp: Date.now() });
  if (openedLinks.value.length > 20) openedLinks.value.length = 20;
  addLog('Launcher', `Openlink gestart voor ${module.name}.`, 'info');
}
function clearLogs() {
  globalLogs.value = [];
  addLog('Launcher', 'Lokale launcherlog gewist.', 'warning');
}
function triggerPanic() {
  if (panicLocked.value || !window.confirm('Noodstop: trek lokale launcher-verificaties in en wis de lokale sessiestatus? Andere browsertabs kunnen niet worden gesloten.')) return;
  verifier.suspend();
  for (const module of modules) verifier.changeInput(module, '');
  openedLinks.value = [];
  panicLocked.value = true;
  addLog('Noodstop', 'Lokale verificaties ingetrokken. Andere browsertabs zijn niet gesloten.', 'critical');
}
function checkReturn() { verifier.suspend(); clockTick.value++; }
function onVisibility() { checkReturn(); }
function onPageShow(event) { if (event.persisted) checkReturn(); }

onMounted(() => {
  tickTimer = setInterval(() => { verifier.refreshAll(); clockTick.value++; }, 250);
  addLog('Launcher', 'PALACO NEO gestart; alleen lokale launcher-events worden bijgehouden.', 'success');
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
        <p class="eyebrow">NEO // COMMANDO CENTRUM</p>
        <h1>PALACO NEO</h1>
        <span class="subtitle">NIEUWE REALITEIT // EVOLUTIE GESTART</span>
      </div>
      <div class="system-status" role="status">
        <span class="status-dot" :class="globalStatusClass" aria-hidden="true"></span>
        {{ globalStatusText }}
      </div>
      <div class="system-metrics" aria-label="Lokale launchersessie">
        <span>Launcher-verificatie <strong :class="sessionValid ? 'ok' : 'expired'">{{ sessionValid ? `Geldig · ${sessionRemaining}s` : 'Niet actief' }}</strong></span>
        <span>Modules geopend <strong>{{ launchedModuleCount }} / {{ modules.length }}</strong></span>
      </div>
    </header>

    <main>
      <aside class="preview-note" aria-label="Previewstatus">
        <strong>PREVIEW — GEEN ACCEPTATIE / PRODUCTIE</strong>
        <p>Dit is de launcher. AETHER, BASTION en 5CRIPTIE zijn nog niet als werkende apps overgedragen.</p>
        <p>Agenda-uitvoering is geblokkeerd. Deze preview verleent geen toestemming om afspraken te wijzigen.</p>
        <p>Status en audit hieronder gelden alleen voor deze launcher. Er is geen module-heartbeat of ecosysteembreed audit-endpoint.</p>
      </aside>
      <aside v-if="panicLocked" class="panic-state" role="alert">
        <strong>LOKALE NOODSTOP ACTIEF</strong>
        <p>Launcher-verificaties en de lokale openingslijst zijn gewist. Reeds geopende externe tabs zijn niet gesloten; herlaad deze pagina om opnieuw te beginnen.</p>
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
              :disabled="panicLocked" :aria-invalid="!!module.error" :aria-describedby="`detail-${module.id}`"
              @input="verifier.changeInput(module, $event.target.value)" />
            <div class="config-actions">
              <button type="button" data-verify :disabled="panicLocked || !module.isValid || module.isVerifying" @click="verifyModule(module)">
                {{ module.isVerifying ? 'Controleren…' : 'Opslaan & verifiëren' }}
              </button>
              <button v-if="module.isVerifying" type="button" class="cancel-btn" data-cancel @click="verifier.cancel(module)">Annuleren</button>
            </div>
            <div :id="`detail-${module.id}`" class="details" aria-live="polite">
              <p v-if="module.error" class="error-msg">{{ module.error }}</p>
              <div v-if="module.lastCheck" class="check-details">
                <span>Laatste check: {{ localTime(module.lastCheck.time) }}</span>
                <span v-if="module.lastCheck.result === 'success'" class="success-detail">ID bevestigd: {{ module.lastCheck.receivedId }}</span>
                <span data-latency>Checkduur: {{ module.checkLatencyMs == null ? '—' : `${module.checkLatencyMs} ms` }}</span>
                <span data-tls>HTTPS-handshake: {{ module.tlsStatus === 'accepted' ? 'geaccepteerd door browser' : 'niet bevestigd' }}</span>
              </div>
            </div>
            <p v-if="module.status === 'verified'" class="expiry-timer" data-countdown>Vervalt over {{ remaining(module) }}s</p>
          </div>
          <button type="button" class="launch-btn" data-launch :disabled="panicLocked || module.status !== 'verified'" @click="openModule(module)">
            {{ module.status === 'verified' ? 'Open module' : 'Wacht op verificatie' }}
          </button>
        </article>
      </div>
      <section class="operations-panels" aria-label="Lokale launcher-activiteit">
        <div class="audit-panel">
          <div class="panel-header">
            <h2>LOKALE LAUNCHERLOG</h2>
            <button type="button" class="clear-log" @click="clearLogs">Wis lokale log</button>
          </div>
          <p class="panel-note">Niet verbonden met AETHER- of BASTION-auditdata; deze lijst verdwijnt bij herladen.</p>
          <ol v-if="globalLogs.length" class="log-list">
            <li v-for="log in globalLogs" :key="log.id" class="log-entry" :class="log.type">
              <time>{{ localTime(log.timestamp) }}</time>
              <strong>[{{ log.source }}]</strong>
              <span>{{ log.message }}</span>
            </li>
          </ol>
          <p v-else class="empty-log">Geen lokale launcher-events.</p>
        </div>
        <div class="opened-panel">
          <h2>RECENTE OPENLINKS</h2>
          <p class="panel-note">De browser deelt niet of een externe tab nog open is.</p>
          <ol v-if="openedLinks.length" class="log-list">
            <li v-for="(link, index) in openedLinks" :key="`${link.moduleId}-${link.timestamp}-${index}`" class="log-entry">
              <time>{{ localTime(link.timestamp) }}</time>
              <strong>{{ link.name }}</strong>
              <span>Openverzoek gestart</span>
            </li>
          </ol>
          <p v-else class="empty-log">Nog geen openverzoeken.</p>
        </div>
      </section>
    </main>

    <footer class="palaco-footer">
      <p>Een succesvolle check toont alleen dat de toegestane HTTPS-origin metadata met de verwachte appId teruggaf.</p>
      <p>Latency is de gemeten duur van die check. Certificaatverval en periodieke module-heartbeats worden niet gemeten.</p>
      <p>Er is geen gedeelde auditfeed, authenticatie, autorisatie of mogelijkheid om externe tabs te sluiten.</p>
      <button type="button" class="panic-button" :disabled="panicLocked" @click="triggerPanic">
        🚨 {{ panicLocked ? 'NOODSTOP ACTIEF' : 'LOKALE NOODSTOP' }}
      </button>
      <p>Een bevestiging vervalt na maximaal 60 seconden. Bij terugkeer naar deze pagina verifieer je opnieuw.</p>
    </footer>
  </div>
</template>
