<script setup>
import { ref, watch } from 'vue';
import { encryptMessage } from './crypto.js';
import { createBastionTask } from './bastion.js';
import { createRevisionGuard } from './revision.js';
import { createEncryptedExport, ENCRYPTED_EXPORT_FILENAME } from './export.js';
import { readEncryptedImport } from './import.js';

const message = ref('');
const passphrase = ref('');
const encrypted = ref('');
const encrypting = ref(false);
const importing = ref(false);
const sending = ref(false);
const sent = ref(false);
const notice = ref('');
const error = ref('');
const inputGuard = createRevisionGuard();

// Never offer a ciphertext for transmission after its source fields change.
watch([message, passphrase], () => {
  inputGuard.invalidate();
  encrypted.value = '';
  sent.value = false;
  notice.value = '';
  error.value = '';
}, { flush: 'sync' });

async function encrypt() {
  if (encrypting.value || importing.value || sending.value) return;
  encrypted.value = '';
  notice.value = '';
  error.value = '';
  sent.value = false;
  encrypting.value = true;
  const revision = inputGuard.snapshot();
  try {
    const result = await encryptMessage(message.value, passphrase.value);
    if (!inputGuard.isCurrent(revision)) return;
    // Clear the form before publishing the new ciphertext: the watcher will
    // invalidate any previous result, but not the result assigned below.
    message.value = '';
    passphrase.value = '';
    encrypted.value = result;
    notice.value = 'Versleuteld. De leesbare invoer is uit het formulier verwijderd.';
  } catch {
    if (inputGuard.isCurrent(revision)) {
      error.value = 'Versleutelen mislukt. Vul een bericht (max. 16.000 tekens) en een passphrase van minimaal 12 tekens in.';
    }
  } finally {
    encrypting.value = false;
  }
}

async function importEncrypted(event) {
  const input = event.target;
  const file = input.files?.[0];
  input.value = '';
  if (!file || encrypting.value || sending.value) return;

  inputGuard.invalidate();
  const revision = inputGuard.snapshot();
  encrypted.value = '';
  sent.value = false;
  notice.value = '';
  error.value = '';
  importing.value = true;
  try {
    const result = await readEncryptedImport(file);
    if (!inputGuard.isCurrent(revision)) return;
    encrypted.value = result;
    notice.value = 'Versleuteld bestand lokaal geladen. Er is niets verstuurd. Bewaar de passphrase afzonderlijk.';
  } catch {
    if (inputGuard.isCurrent(revision)) {
      error.value = 'Import geweigerd: ongeldig, beschadigd of te groot versleuteld bestand.';
    }
  } finally {
    importing.value = false;
  }
}

function downloadEncrypted() {
  if (!encrypted.value || importing.value || sending.value) return;
  try {
    const blob = createEncryptedExport(encrypted.value);
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = ENCRYPTED_EXPORT_FILENAME;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice.value = 'Versleuteld bestand aangeboden voor lokaal opslaan. Bewaar de passphrase afzonderlijk.';
    error.value = '';
  } catch {
    error.value = 'Lokaal exporteren is niet gelukt.';
  }
}

function clearResult() {
  if (importing.value || sending.value) return;
  encrypted.value = '';
  sent.value = false;
  notice.value = '';
  error.value = '';
}

async function send() {
  if (importing.value || sending.value || sent.value || !encrypted.value) return;
  sending.value = true;
  error.value = '';
  notice.value = '';
  try {
    const task = await createBastionTask(encrypted.value);
    sent.value = true;
    notice.value = `Bastion-demotaak aangemaakt (${task.id}).`;
  } catch (failure) {
    error.value = failure.message;
  } finally {
    sending.value = false;
  }
}
</script>

<template>
  <main>
    <h1>AETHER</h1>
    <p>Lokale demo — geen productiegegevens. Alleen het versleutelde resultaat wordt op verzoek verstuurd.</p>
    <form @submit.prevent="encrypt">
      <label for="message">Bericht</label>
      <textarea id="message" v-model="message" required maxlength="16000" :disabled="encrypting || importing || sending"></textarea>
      <label for="passphrase">Passphrase (minimaal 12 tekens; bewaar deze zelf)</label>
      <input id="passphrase" v-model="passphrase" type="password" minlength="12" required autocomplete="new-password" :disabled="encrypting || sending" />
      <button :disabled="encrypting || sending">{{ encrypting ? 'Versleutelen…' : 'Versleutel' }}</button>
    </form>
    <section aria-labelledby="import-label">
      <h2 id="import-label">Lokaal versleuteld bestand openen</h2>
      <p>Alleen AETHER-envelop v1 (maximaal 64 KiB). Geen automatische verzending of ontsleuteling.</p>
      <label for="encrypted-file">Kies een versleuteld JSON-bestand</label>
      <input id="encrypted-file" type="file" accept=".json,application/json" @change="importEncrypted" :disabled="encrypting || importing || sending" />
      <p v-if="importing" role="status">Bestand controleren…</p>
    </section>
    <section v-if="encrypted" aria-labelledby="result">
      <h2 id="result">Versleuteld resultaat</h2>
      <textarea aria-label="Versleutelde tekst" :value="encrypted" readonly></textarea>
      <button @click="send" :disabled="importing || sending || sent" :aria-busy="sending">{{ sending ? 'Versturen…' : sent ? 'Verstuurd' : 'Send to Bastion' }}</button>
      <button type="button" @click="downloadEncrypted" :disabled="importing || sending">Bewaar versleuteld bestand</button>
      <button type="button" @click="clearResult" :disabled="importing || sending">Wis versleuteld resultaat</button>
    </section>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </main>
</template>
