import { isEncryptedEnvelope, MAX_ENVELOPE_LENGTH } from './envelope.js';

export async function readEncryptedImport(file) {
  if (!file || !Number.isSafeInteger(file.size) || file.size < 1
    || file.size > MAX_ENVELOPE_LENGTH || typeof file.text !== 'function') {
    throw new Error('Ongeldig of te groot importbestand.');
  }
  const text = await file.text();
  if (!isEncryptedEnvelope(text)
    || new TextEncoder().encode(text).byteLength > MAX_ENVELOPE_LENGTH) {
    throw new Error('Het bestand bevat geen geldige AETHER-envelop.');
  }
  return text;
}
