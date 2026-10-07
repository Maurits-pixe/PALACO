<script setup>
import { computed, onUnmounted, ref } from 'vue';

const tasks = ref([
  { id: 1, title: 'Beveiliging Perimeter Oost', description: 'Controleer sensoren sector 4–9.', priority: 'HIGH', status: 'ACTIVE', assignee: 'Alpha Team', clearance: 3 },
  { id: 2, title: 'Decryptie Data Packet #402', description: 'Analyseer hoofdheader voor signatures.', priority: 'CRITICAL', status: 'ACTIVE', assignee: 'Tech Ops', clearance: 5 },
  { id: 3, title: 'Logistieke Voorraad Check', description: 'Inventarisatie unit 7.', priority: 'MEDIUM', status: 'PENDING', assignee: 'Support', clearance: 1 },
]);
const messages = ref([
  { id: 1, sender: 'Cmdr. Shepard', text: 'Team, bevestig status van Sector 7.', time: '10:42' },
  { id: 2, sender: 'Lt. Koenig', text: 'Sector 7 veilig. Beweeg naar rendezvous.', time: '10:44' },
]);
const auditLogs = ref([
  { id: 1, time: '10:40:01', action: 'LOGIN_SUCCESS (FIXTURE)', user: 'Preview', type: 'info' },
  { id: 2, time: '10:41:15', action: 'VIEW_TASKS (FIXTURE)', user: 'Preview', type: 'info' },
]);
const newMessage = ref('');
const pendingMutation = ref(null);
const blockedMessage = ref('');
let timer;

const activeCount = computed(() => tasks.value.filter(task => task.status !== 'COMPLETED').length);

function initiateMutation(action, task) {
  blockedMessage.value = '';
  pendingMutation.value = { action, task };
}

function confirmMutation() {
  // This preview intentionally has no mutation backend and never changes task state.
  blockedMessage.value = 'Uitvoering geblokkeerd: STORAGE_EFFECT_DEADLINE_UNSUPPORTED. Er is geen ticket geconsumeerd en geen taak gewijzigd.';
  auditLogs.value.unshift({ id: crypto.randomUUID(), time: new Date().toLocaleTimeString(), action: 'MUTATION_BLOCKED_STORAGE_DEADLINE', user: 'Preview', type: 'blocked' });
  pendingMutation.value = null;
  clearTimeout(timer);
}

function cancelMutation() { pendingMutation.value = null; clearTimeout(timer); }

function sendMessage() {
  const text = newMessage.value.trim();
  if (!text) return;
  messages.value.push({ id: crypto.randomUUID(), sender: 'Preview', text, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
  newMessage.value = '';
  auditLogs.value.unshift({ id: crypto.randomUUID(), time: new Date().toLocaleTimeString(), action: 'LOCAL_MESSAGE_FIXTURE', user: 'Preview', type: 'info' });
}

onUnmounted(() => clearTimeout(timer));
</script>

<template>
  <div class="bastion-container">
    <header class="command-header">
      <div class="brand"><div class="logo-icon" aria-hidden="true">🛡️</div><div><h1>CITADEL BASTION</h1><span class="subtitle">TACTISCH COMMANDOCENTRUM // PREVIEW ONLY</span></div></div>
      <div class="system-status"><span class="dot"></span><span>PREVIEW — GEEN ACCEPTATIE / PRODUCTIE</span></div>
    </header>

    <div class="preview-banner" role="status"><strong>Mutaties zijn gesloten.</strong> Deze overdracht bevat alleen fixturedata. Bevestigen voert niets uit zolang de opslagdeadline niet bewezen is.</div>
    <p v-if="blockedMessage" class="blocked-banner" role="alert">{{ blockedMessage }}</p>

    <main class="grid-layout">
      <section class="panel tasks-panel"><div class="panel-header"><h2>HUIDIGE OPERATIES</h2><span class="badge">{{ activeCount }} FIXTURES</span></div>
        <div class="task-list"><article v-for="task in tasks" :key="task.id" class="task-card" :class="task.priority">
          <div class="task-header"><span class="task-title">{{ task.title }}</span><span class="priority-badge">{{ task.priority }}</span></div>
          <p class="task-desc">{{ task.description }}</p><div class="task-meta"><span>ASSIGNED: {{ task.assignee }}</span><span>CLEARANCE: L{{ task.clearance }}</span></div>
          <div class="task-actions"><button v-if="task.status !== 'COMPLETED'" @click="initiateMutation('COMPLETE', task)" class="btn-sm btn-success">Afronden</button><button v-if="task.priority === 'MEDIUM'" @click="initiateMutation('ESCALATE', task)" class="btn-sm btn-warning">Escaleren</button></div>
        </article></div>
      </section>

      <div class="right-col"><section class="panel chat-panel"><div class="panel-header"><h2>SECURE COMMS (FIXTURE)</h2><span class="timer-warning">GEEN PRODUCTIEKANAAL</span></div><div class="chat-window"><div v-for="msg in messages" :key="msg.id" class="message"><span class="sender">{{ msg.sender }}:</span><p>{{ msg.text }}</p><span class="time">{{ msg.time }}</span></div></div><div class="chat-input"><input v-model="newMessage" @keyup.enter="sendMessage" placeholder="Lokaal fixturebericht…" aria-label="Lokaal fixturebericht" /><button @click="sendMessage">VERZEND</button></div></section>
        <section class="panel log-panel"><div class="panel-header"><h2>AUDIT LOG (FIXTURE)</h2></div><div class="log-list"><div v-for="log in auditLogs" :key="log.id" class="log-entry"><span class="log-time">{{ log.time }}</span><span class="log-action" :class="log.type">{{ log.action }}</span><span class="log-user">{{ log.user }}</span></div></div></section>
      </div>
    </main>

    <div v-if="pendingMutation" class="modal-overlay" role="dialog" aria-modal="true"><div class="modal"><h3>VOORSTEL — NIET UITVOERBAAR</h3><p class="warning-text">Dit is een lokale preview. Het voorstel vereist een bewezen opslagdeadline voordat een echte mutatie-ingang mag worden geopend.</p><div class="mutation-details"><p><strong>Actie:</strong> {{ pendingMutation.action }}</p><p><strong>Doel:</strong> {{ pendingMutation.task.title }}</p></div><div class="modal-actions"><button @click="confirmMutation" class="btn-confirm">TOON BLOKKERING</button><button @click="cancelMutation" class="btn-cancel">ANNULEREN</button></div></div></div>
  </div>
</template>
