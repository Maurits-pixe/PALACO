<script setup>
import { ref } from 'vue';
import { encryptMessage } from './crypto.js';
import { createBastionTask } from './bastion.js';

const message = ref('');
const passphrase = ref('');
const encrypted = ref('');
const encrypting = ref(false);
const sending = ref(false);
const sent = ref(false);
const notice = ref('');
const error = ref('');

async function encrypt() {
  if (encrypting.value || sending.value) return;
  encrypted.value = '';
  notice.value = '';
  error.value = '';
  sent.value = false;
  encrypting.value = true;
  try {
    encrypted.value = await encryptMessage(message.value, passphrase.value);
    passphrase.value = '';
  } catch {
    error.value = 'Versleutelen mislukt. Vul een bericht (max. 16.000 tekens) en een passphrase van minimaal 12 tekens in.';
  } finally {
    encrypting.value = false;
  }
}

async function send() {
  if (sending.value || sent.value || !encrypted.value) return;
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
      <textarea id="message" v-model="message" required maxlength="16000" :disabled="encrypting || sending"></textarea>
      <label for="passphrase">Passphrase (minimaal 12 tekens; bewaar deze zelf)</label>
      <input id="passphrase" v-model="passphrase" type="password" minlength="12" required autocomplete="new-password" :disabled="encrypting || sending" />
      <button :disabled="encrypting || sending">{{ encrypting ? 'Versleutelen…' : 'Versleutel' }}</button>
    </form>
    <section v-if="encrypted" aria-labelledby="result">
      <h2 id="result">Versleuteld resultaat</h2>
      <textarea aria-label="Versleutelde tekst" :value="encrypted" readonly></textarea>
      <button @click="send" :disabled="sending || sent" :aria-busy="sending">{{ sending ? 'Versturen…' : 'Send to Bastion' }}</button>
    </section>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </main>
</template>
