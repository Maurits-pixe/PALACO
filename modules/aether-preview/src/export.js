import { isEncryptedEnvelope } from './envelope.js';

export const ENCRYPTED_EXPORT_FILENAME = 'aether-envelope-v1.json';

export function createEncryptedExport(envelope) {
  if (!isEncryptedEnvelope(envelope)) {
    throw new Error('Alleen een geldige versleutelde envelop kan worden geëxporteerd.');
  }
  return new Blob([envelope], { type: 'application/json' });
}
