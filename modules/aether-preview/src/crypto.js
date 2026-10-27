const encode = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes)));

export async function encryptMessage(message, passphrase) {
  if (typeof message !== 'string' || !message.trim() || message.length > 16000
    || typeof passphrase !== 'string' || passphrase.length < 12) {
    throw new Error('Invalid encryption input');
  }
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const material = await crypto.subtle.importKey('raw', new TextEncoder().encode(passphrase), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 310000 },
    material, { name: 'AES-GCM', length: 256 }, false, ['encrypt'],
  );
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(message));
  return JSON.stringify({
    version: 1, algorithm: 'AES-GCM', kdf: 'PBKDF2-SHA-256', iterations: 310000,
    salt: encode(salt), iv: encode(iv), ciphertext: encode(ciphertext),
  });
}
