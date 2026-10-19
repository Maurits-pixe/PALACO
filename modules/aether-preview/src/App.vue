<script setup>
import { computed, onMounted, ref } from 'vue';
import {
  decryptBytes,
  encryptBytes,
  MAX_FILE_BYTES,
  MAX_PASSPHRASE_LENGTH,
  MIN_PASSPHRASE_LENGTH,
  validateEnvelope
} from './crypto.js';
import { clearVault, listVaultItems, removeVaultItem, saveVaultItem } from './vault.js';

const selectedFile = ref(null);
const encryptPassphrase = ref('');
const confirmPassphrase = ref('');
const decryptPassphrase = ref('');
const vaultItems = ref([]);
const busy = ref(false);
const cryptoAvailable = ref(false);
const vaultAvailable = ref(false);
const message = ref('');
const errorMessage = ref('');

const systemReady = computed(() => cryptoAvailable.value && vaultAvailable.value);

function selectFile(event) {
  selectedFile.value = event.target.files?.[0] ?? null;
  message.value = '';
  errorMessage.value = '';
}

async function refreshVault() {
  try {
    vaultItems.value = await listVaultItems();
    vaultAvailable.value = true;
  } catch (error) {
    vaultAvailable.value = false;
    errorMessage.value = error.message;
  }
}

function packFile(file, bytes) {
  const header = new TextEncoder().encode(JSON.stringify({
    name: file.name,
    type: file.type || 'application/octet-stream'
  }));
  const packed = new Uint8Array(4 + header.length + bytes.length);
  new DataView(packed.buffer).setUint32(0, header.length);
  packed.set(header, 4);
  packed.set(bytes, 4 + header.length);
  return packed;
}

function unpackFile(packed) {
  if (packed.byteLength < 4) throw new Error('Het ontsleutelde bestand is ongeldig.');
  const headerLength = new DataView(packed.buffer, packed.byteOffset, packed.byteLength).getUint32(0);
  if (headerLength > packed.byteLength - 4) throw new Error('Het ontsleutelde bestand is ongeldig.');
  const headerStart = 4;
  const headerEnd = headerStart + headerLength;
  let header;
  try {
    header = JSON.parse(new TextDecoder().decode(packed.subarray(headerStart, headerEnd)));
  } catch {
    throw new Error('De versleutelde bestandsmetadata is ongeldig.');
  }
  if (typeof header.name !== 'string' || typeof header.type !== 'string') {
    throw new Error('De versleutelde bestandsmetadata is ongeldig.');
  }
  const name = header.name.split(/[\\/]/).pop().replace(/[\u0000-\u001f\u007f]/g, '') || 'ontsleuteld-bestand';
  return { name, type: 'application/octet-stream', bytes: packed.slice(headerEnd) };
}

async function encryptSelectedFile() {
  message.value = '';
  errorMessage.value = '';
  if (!selectedFile.value) {
    errorMessage.value = 'Kies eerst een bestand.';
    return;
  }
  if (encryptPassphrase.value !== confirmPassphrase.value) {
    errorMessage.value = 'De wachtzinnen komen niet overeen.';
    return;
  }
  if (selectedFile.value.size > MAX_FILE_BYTES) {
    errorMessage.value = 'Bestanden mogen maximaal 25 MiB groot zijn.';
    return;
  }
  busy.value = true;
  try {
    const bytes = new Uint8Array(await selectedFile.value.arrayBuffer());
    const envelope = await encryptBytes(packFile(selectedFile.value, bytes), encryptPassphrase.value);
    const id = crypto.randomUUID();
    await saveVaultItem({ id, envelope });
    selectedFile.value = null;
    encryptPassphrase.value = '';
    confirmPassphrase.value = '';
    const fileInput = document.querySelector('#file-to-encrypt');
    if (fileInput) fileInput.value = '';
    await refreshVault();
    message.value = 'Bestand versleuteld en lokaal opgeslagen. De wachtzin is niet bewaard.';
  } catch (error) {
    errorMessage.value = error.message || 'Versleutelen is mislukt.';
  } finally {
    busy.value = false;
  }
}

async function decryptVaultItem(item) {
  message.value = '';
  errorMessage.value = '';
  busy.value = true;
  try {
    const packed = await decryptBytes(item.envelope, decryptPassphrase.value);
    const file = unpackFile(packed);
    const downloadUrl = URL.createObjectURL(new Blob([file.bytes], { type: file.type }));
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = file.name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    decryptPassphrase.value = '';
    message.value = 'Bestand lokaal ontsleuteld en als download aangeboden.';
  } catch (error) {
    errorMessage.value = error.message || 'Ontsleutelen is mislukt.';
  } finally {
    busy.value = false;
  }
}

function exportVaultItem(item) {
  const blob = new Blob([JSON.stringify(item.envelope)], { type: 'application/json' });
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = downloadUrl;
  link.download = `aether-${item.id}.aether.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
  message.value = 'Versleutelde back-up gedownload. Bewaar ook de wachtzin apart.';
  errorMessage.value = '';
}

async function importEncryptedBackup(event) {
  message.value = '';
  errorMessage.value = '';
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (file.size > MAX_FILE_BYTES * 1.4) {
    errorMessage.value = 'Back-upbestand is groter dan toegestaan.';
    return;
  }
  busy.value = true;
  try {
    const envelope = JSON.parse(await file.text());
    validateEnvelope(envelope);
    await saveVaultItem({ id: crypto.randomUUID(), envelope });
    await refreshVault();
    message.value = 'Versleutelde back-up geïmporteerd. Ontsleutelen vereist de oorspronkelijke wachtzin.';
  } catch (error) {
    errorMessage.value = error.message || 'Back-up importeren is mislukt.';
  } finally {
    busy.value = false;
  }
}

async function deleteVaultItem(id) {
  if (!window.confirm('Verwijder dit versleutelde bestand uit deze browser?')) return;
  try {
    await removeVaultItem(id);
    await refreshVault();
    message.value = 'Versleuteld bestand uit de lokale browserkluis verwijderd.';
    errorMessage.value = '';
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function clearAllVaultItems() {
  if (!window.confirm('Verwijder alle versleutelde bestanden uit deze browserkluis?')) return;
  try {
    await clearVault();
    await refreshVault();
    message.value = 'Alle versleutelde bestanden zijn uit deze browserkluis verwijderd.';
    errorMessage.value = '';
  } catch (error) {
    errorMessage.value = error.message;
  }
}

onMounted(async () => {
  cryptoAvailable.value = Boolean(globalThis.crypto?.subtle && globalThis.crypto?.getRandomValues);
  await refreshVault();
});
</script>

<template>
  <div class="aether-shell">
    <div class="grid-backdrop" aria-hidden="true"></div>
    <header class="topbar">
      <a class="brand" href="/" aria-label="AETHER startpagina">
        <span class="brand-mark" aria-hidden="true">◈</span>
        <span><strong>AETHER</strong><small>LOKALE CRYPTOGRAFISCHE KLUIS</small></span>
      </a>
      <span class="preview-tag">GEÏSOLEERDE PREVIEW</span>
    </header>

    <main class="workspace">
      <section class="intro">
        <p class="eyebrow">PALACO // BEVEILIGDE BESTANDSVERWERKING</p>
        <h1>Jouw bestanden.<br /><span>Versleuteld in je browser.</span></h1>
        <p class="lede">AETHER versleutelt lokaal met AES-256-GCM en een wachtzin. Bestandsinhoud wordt niet geüpload; de kluis bewaart alleen versleutelde data in deze browser.</p>
      </section>

      <section class="status-panel" aria-labelledby="status-title">
        <div class="section-heading">
          <div><span class="section-index">01</span><h2 id="status-title">Systeemstatus</h2></div>
          <span class="status-pill" :class="{ ready: systemReady }"><i></i>{{ systemReady ? 'LOKAAL BESCHIKBAAR' : 'NIET BESCHIKBAAR' }}</span>
        </div>
        <div class="status-grid">
          <div><span>Cryptografie</span><strong :class="{ good: cryptoAvailable }">{{ cryptoAvailable ? 'Web Crypto actief' : 'Niet beschikbaar' }}</strong></div>
          <div><span>Lokale kluis</span><strong :class="{ good: vaultAvailable }">{{ vaultAvailable ? 'IndexedDB actief' : 'Niet beschikbaar' }}</strong></div>
          <div><span>Versleutelde bestanden</span><strong>{{ vaultItems.length }}</strong></div>
          <div><span>Algoritme</span><strong>AES-GCM-256</strong></div>
        </div>
      </section>

      <section class="work-grid">
        <form class="panel" @submit.prevent="encryptSelectedFile">
          <div class="section-heading">
            <div><span class="section-index">02</span><h2>Bestand versleutelen</h2></div>
            <span class="algorithm">AES-256-GCM</span>
          </div>
          <label class="field-label" for="file-to-encrypt">Bestand <small>MAX. 25 MiB</small></label>
          <input id="file-to-encrypt" type="file" :disabled="busy || !systemReady" @change="selectFile" />
          <p v-if="selectedFile" class="selected-file">Geselecteerd: {{ selectedFile.name }} ({{ (selectedFile.size / 1024 / 1024).toFixed(2) }} MiB)</p>
          <label class="field-label" for="passphrase">Wachtzin <small>MIN. {{ MIN_PASSPHRASE_LENGTH }} TEKENS</small></label>
          <input
            id="passphrase"
            v-model="encryptPassphrase"
            type="password"
            autocomplete="new-password"
            :minlength="MIN_PASSPHRASE_LENGTH"
            :maxlength="MAX_PASSPHRASE_LENGTH"
            :disabled="busy || !systemReady"
            placeholder="Gebruik een unieke, sterke wachtzin"
          />
          <label class="field-label" for="confirm-passphrase">Bevestig wachtzin</label>
          <input
            id="confirm-passphrase"
            v-model="confirmPassphrase"
            type="password"
            autocomplete="new-password"
            :minlength="MIN_PASSPHRASE_LENGTH"
            :maxlength="MAX_PASSPHRASE_LENGTH"
            :disabled="busy || !systemReady"
            placeholder="Voer dezelfde wachtzin opnieuw in"
          />
          <p class="field-help">De wachtzin verlaat deze pagina niet en wordt niet opgeslagen. AETHER kan verloren wachtzinnen niet herstellen.</p>
          <button class="primary-button" type="submit" :disabled="busy || !systemReady">
            {{ busy ? 'BEZIG…' : 'VERSLEUTEL EN BEWAAR LOKAAL' }}
          </button>
        </form>

        <section class="panel vault-panel" aria-labelledby="vault-title">
          <div class="section-heading">
            <div><span class="section-index">03</span><h2 id="vault-title">Bestandskluis</h2></div>
            <div class="vault-heading-actions">
              <span class="vault-count">{{ vaultItems.length }} ITEM{{ vaultItems.length === 1 ? '' : 'S' }}</span>
              <button
                v-if="vaultItems.length"
                class="delete-all-button"
                type="button"
                :disabled="busy"
                @click="clearAllVaultItems"
              >WIS KLUIS</button>
            </div>
          </div>
          <label class="backup-import">
            <span>IMPORTEER VERSLEUTELDE BACK-UP</span>
            <input
              type="file"
              accept=".json,application/json"
              :disabled="busy || !systemReady"
              @change="importEncryptedBackup"
            />
          </label>
          <label class="field-label" for="vault-passphrase">Wachtzin voor ontsleutelen</label>
          <input
            id="vault-passphrase"
            v-model="decryptPassphrase"
            type="password"
            autocomplete="current-password"
            :minlength="MIN_PASSPHRASE_LENGTH"
            :maxlength="MAX_PASSPHRASE_LENGTH"
            :disabled="busy || !systemReady"
            placeholder="Vul dezelfde wachtzin in"
          />
          <p v-if="vaultItems.length === 0" class="empty-state">Nog geen versleutelde bestanden in deze browser.</p>
          <ul v-else class="vault-list">
            <li v-for="item in vaultItems" :key="item.id">
              <span><strong>VERSLEUTELD BESTAND</strong><small>ID {{ item.id.slice(0, 8) }}</small></span>
              <div class="item-actions">
                <button class="text-button" type="button" :disabled="busy" @click="exportVaultItem(item)">BACK-UP</button>
                <button class="text-button" type="button" :disabled="busy" @click="decryptVaultItem(item)">ONTGRENDEL</button>
                <button class="delete-button" type="button" :disabled="busy" :aria-label="`Verwijder item ${item.id.slice(0, 8)}`" @click="deleteVaultItem(item.id)">×</button>
              </div>
            </li>
          </ul>
        </section>
      </section>

      <p v-if="message" class="feedback success" role="status">{{ message }}</p>
      <p v-if="errorMessage" class="feedback error" role="alert">{{ errorMessage }}</p>

      <aside class="notice">
        <strong>Preview — geen beveiligingscertificering.</strong>
        <span>Kluisdata blijft versleuteld in IndexedDB; de item-ID en cryptografische parameters zijn zichtbaar voor deze browser. Verwijdering via de app is geen gegarandeerde veilige verwijdering uit opslagmedia. Dit is geen productiekluis, back-up of vervanging voor een onafhankelijke security review.</span>
      </aside>
    </main>
  </div>
</template>
