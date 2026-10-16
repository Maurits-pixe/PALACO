export const MIN_PASSPHRASE_LENGTH = 12;
export const MAX_FILE_BYTES = 25 * 1024 * 1024;
const KDF_ITERATIONS = 310_000;
const ENCODER = new TextEncoder();

function requirePassphrase(passphrase) {
  if (typeof passphrase !== 'string' || [...passphrase].length < MIN_PASSPHRASE_LENGTH) {
    throw new Error(`Gebruik een wachtzin van minimaal ${MIN_PASSPHRASE_LENGTH} tekens.`);
  }
}

function toBase64(bytes) {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function fromBase64(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, character => character.charCodeAt(0));
}

async function deriveKey(passphrase, salt, cryptoImpl) {
  const material = await cryptoImpl.subtle.importKey(
    'raw',
    ENCODER.encode(passphrase),
    'PBKDF2',
    false,
    ['deriveKey']
  );
  return cryptoImpl.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: KDF_ITERATIONS },
    material,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt']
  );
}

export async function encryptBytes(bytes, passphrase, cryptoImpl = globalThis.crypto) {
  requirePassphrase(passphrase);
  if (!cryptoImpl?.subtle || !cryptoImpl?.getRandomValues) {
    throw new Error('Web Crypto is niet beschikbaar in deze browsercontext.');
  }
  if (!(bytes instanceof Uint8Array) || bytes.byteLength > MAX_FILE_BYTES + 64 * 1024) {
    throw new Error('Bestand moet een byte-array zijn van maximaal 25 MiB.');
  }

  const salt = cryptoImpl.getRandomValues(new Uint8Array(16));
  const iv = cryptoImpl.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(passphrase, salt, cryptoImpl);
  const ciphertext = await cryptoImpl.subtle.encrypt({ name: 'AES-GCM', iv }, key, bytes);
  return {
    schema: 'aether.v1',
    cipher: 'AES-GCM-256',
    kdf: 'PBKDF2-SHA-256',
    iterations: KDF_ITERATIONS,
    salt: toBase64(salt),
    iv: toBase64(iv),
    ciphertext: toBase64(new Uint8Array(ciphertext))
  };
}

export async function decryptBytes(envelope, passphrase, cryptoImpl = globalThis.crypto) {
  requirePassphrase(passphrase);
  if (!cryptoImpl?.subtle) {
    throw new Error('Web Crypto is niet beschikbaar in deze browsercontext.');
  }
  if (
    envelope?.schema !== 'aether.v1' ||
    envelope?.cipher !== 'AES-GCM-256' ||
    envelope?.kdf !== 'PBKDF2-SHA-256' ||
    envelope?.iterations !== KDF_ITERATIONS
  ) {
    throw new Error('Onbekend of ongeldig AETHER-kluisformaat.');
  }

  const salt = fromBase64(envelope.salt);
  const iv = fromBase64(envelope.iv);
  const ciphertext = fromBase64(envelope.ciphertext);
  if (salt.byteLength !== 16 || iv.byteLength !== 12 || ciphertext.byteLength < 16) {
    throw new Error('Onvolledige of beschadigde AETHER-kluisdata.');
  }
  const key = await deriveKey(passphrase, salt, cryptoImpl);
  const plaintext = await cryptoImpl.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
  return new Uint8Array(plaintext);
}
