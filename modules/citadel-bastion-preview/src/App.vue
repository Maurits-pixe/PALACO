<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { io } from 'socket.io-client';

const tasks = ref([
  { id: 1, title: 'Beveiliging Perimeter Oost', description: 'Controleer sensoren sector 4–9.', priority: 'HIGH', status: 'ACTIVE', assignee: 'Alpha Team', clearance: 3 },
  { id: 2, title: 'Decryptie Data Packet #402', description: 'Analyseer hoofdheader voor signatures.', priority: 'CRITICAL', status: 'ACTIVE', assignee: 'Tech Ops', clearance: 5 },
  { id: 3, title: 'Logistieke Voorraad Check', description: 'Inventarisatie unit 7.', priority: 'MEDIUM', status: 'PENDING', assignee: 'Support', clearance: 1 },
]);
const messages = ref([]);
const auditLogs = ref([]);
const newMessage = ref('');
const selfDestruct = ref(false);
const pendingMutation = ref(null);
const blockedMessage = ref('');
const mutationBlockedCode = 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED';
const backendConnected = ref(false);
let socket;
const expiryTimers = new Map();

const activeCount = computed(() => tasks.value.filter(task => task.status !== 'COMPLETED').length);

function initiateMutation(action, task) {
  blockedMessage.value = '';
  pendingMutation.value = { action, task };
}

async function confirmMutation() {
  if (!pendingMutation.value) return;
  const { action, task } = pendingMutation.value;
  try {
    const response = await fetch('/api/mutations/blocked', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, taskId: task.id })
    });
    const result = await response.json();
    blockedMessage.value = `${result.code ?? mutationBlockedCode}: ${result.message ?? 'Mutatie niet uitgevoerd.'}`;
  } catch {
    blockedMessage.value = 'MUTATION_BLOCKED: previewbackend niet beschikbaar; taak niet gewijzigd.';
  }
  pendingMutation.value = null;
}

function cancelMutation() { pendingMutation.value = null; }

function upsertMessage(message) {
  if (message.expires_at && message.expires_at <= Date.now()) {
    removeMessage(message.id);
    return;
  }
  const index = messages.value.findIndex(existing => existing.id === message.id);
  if (index === -1) messages.value.push(message);
  else messages.value[index] = message;
  messages.value.sort((a, b) => a.created_at - b.created_at || a.id - b.id);
  if (message.expires_at) {
    clearTimeout(expiryTimers.get(message.id));
    expiryTimers.set(message.id, setTimeout(() => removeMessage(message.id), Math.max(0, message.expires_at - Date.now())));
  }
}

function removeMessage(id) {
  clearTimeout(expiryTimers.get(id));
  expiryTimers.delete(id);
  messages.value = messages.value.filter(message => message.id !== id);
}

function sendMessage() {
  const text = newMessage.value.trim();
  if (!text || !socket?.connected) return;
  socket.emit('send_message', { text, ttlSeconds: selfDestruct.value ? 30 : null }, result => {
    if (!result?.ok) blockedMessage.value = 'Bericht niet opgeslagen door de previewbackend.';
  });
  newMessage.value = '';
}

function formatTime(timestamp) {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

onMounted(() => {
  socket = io({ path: '/socket.io' });
  socket.on('connect', () => { backendConnected.value = true; });
  socket.on('disconnect', () => { backendConnected.value = false; });
  socket.on('connect_error', () => { backendConnected.value = false; });
  socket.on('init_messages', initialMessages => initialMessages.forEach(upsertMessage));
  socket.on('new_message', upsertMessage);
  socket.on('message_destroyed', ({ id }) => removeMessage(id));
  socket.on('init_audit', logs => { auditLogs.value = logs; });
  socket.on('audit_updated', logs => { auditLogs.value = logs; });
});

onUnmounted(() => {
  socket?.disconnect();
  for (const timer of expiryTimers.values()) clearTimeout(timer);
  expiryTimers.clear();
});
</script>

<template>
  <div class="bastion-container">
    <header class="command-header">
      <div class="brand"><div class="logo-icon" aria-hidden="true">🛡️</div><div><h1>CITADEL BASTION</h1><span class="subtitle">TACTISCH COMMANDOCENTRUM // PREVIEW ONLY</span></div></div>
      <div class="system-status"><span class="dot"></span><span>PREVIEW — GEEN ACCEPTATIE / PRODUCTIE</span></div>
    </header>

    <div class="preview-banner" role="status"><strong>Preview-backend: {{ backendConnected ? 'verbonden' : 'niet verbonden' }}.</strong> Chat, audit en berichtverval werken lokaal via SQLite/Socket.IO. Taakmutaties blijven gesloten; dit is geen D-013-bewijs of productiebackend.</div>
    <p v-if="blockedMessage" class="blocked-banner" role="alert">{{ blockedMessage }}</p>

    <main class="grid-layout">
      <section class="panel tasks-panel"><div class="panel-header"><h2>HUIDIGE OPERATIES</h2><span class="badge">{{ activeCount }} FIXTURES</span></div>
        <div class="task-list"><article v-for="task in tasks" :key="task.id" class="task-card" :class="task.priority">
          <div class="task-header"><span class="task-title">{{ task.title }}</span><span class="priority-badge">{{ task.priority }}</span></div>
          <p class="task-desc">{{ task.description }}</p><div class="task-meta"><span>ASSIGNED: {{ task.assignee }}</span><span>CLEARANCE: L{{ task.clearance }}</span></div>
          <div class="task-actions"><button v-if="task.status !== 'COMPLETED'" @click="initiateMutation('COMPLETE', task)" class="btn-sm btn-success">Afronden</button><button v-if="task.priority === 'MEDIUM'" @click="initiateMutation('ESCALATE', task)" class="btn-sm btn-warning">Escaleren</button></div>
        </article></div>
      </section>

      <div class="right-col"><section class="panel chat-panel"><div class="panel-header"><h2>SECURE COMMS (LOKALE PREVIEW)</h2><span class="timer-warning">GEEN PRODUCTIEKANAAL</span></div><div class="chat-window"><div v-for="msg in messages" :key="msg.id" class="message"><span class="sender">{{ msg.sender }}:</span><p>{{ msg.text }}</p><span class="time">{{ formatTime(msg.created_at) }}<template v-if="msg.expires_at"> · vervalt {{ formatTime(msg.expires_at) }}</template></span></div><p v-if="!messages.length" class="empty-state">Nog geen berichten.</p></div><div class="chat-input"><input v-model="newMessage" @keyup.enter="sendMessage" placeholder="Lokaal previewbericht…" aria-label="Lokaal previewbericht" maxlength="1000" :disabled="!backendConnected" /><label class="self-destruct"><input v-model="selfDestruct" type="checkbox" :disabled="!backendConnected" /> Vervalt na 30s</label><button @click="sendMessage" :disabled="!backendConnected">VERZEND</button></div></section>
        <section class="panel log-panel"><div class="panel-header"><h2>AUDIT LOG (DATABASE)</h2></div><div class="log-list"><div v-for="log in auditLogs" :key="log.id" class="log-entry"><span class="log-time">{{ formatTime(log.timestamp) }}</span><span class="log-action" :class="{ blocked: log.action.startsWith('MUTATION_BLOCKED') }">{{ log.action }} — {{ log.details }}</span><span class="log-user">{{ log.user_id }}</span></div><p v-if="!auditLogs.length" class="empty-state">Nog geen auditgebeurtenissen.</p></div></section>
      </div>
    </main>

    <div v-if="pendingMutation" class="modal-overlay" role="dialog" aria-modal="true"><div class="modal"><h3>VOORSTEL — NIET UITVOERBAAR</h3><p class="warning-text">Dit is een lokale preview. Het voorstel vereist een bewezen opslagdeadline voordat een echte mutatie-ingang mag worden geopend.</p><div class="mutation-details"><p><strong>Actie:</strong> {{ pendingMutation.action }}</p><p><strong>Doel:</strong> {{ pendingMutation.task.title }}</p></div><div class="modal-actions"><button @click="confirmMutation" class="btn-confirm">TOON BLOKKERING</button><button @click="cancelMutation" class="btn-cancel">ANNULEREN</button></div></div></div>
  </div>
</template>
