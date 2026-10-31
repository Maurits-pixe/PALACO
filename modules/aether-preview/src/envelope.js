export const MAX_ENVELOPE_LENGTH = 65536;

export function isEncryptedEnvelope(text) {
  if (typeof text !== 'string' || text.length > MAX_ENVELOPE_LENGTH) return false;
  try {
    const value = JSON.parse(text);
    const base64 = (input, length) => typeof input === 'string'
      && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(input)
      && (length ? atob(input).length === length : atob(input).length >= 17);
    return value !== null
      && Object.keys(value).sort().join(',') === 'algorithm,ciphertext,iterations,iv,kdf,salt,version'
      && value.version === 1 && value.algorithm === 'AES-GCM'
      && value.kdf === 'PBKDF2-SHA-256' && value.iterations === 310000
      && base64(value.salt, 16) && base64(value.iv, 12) && base64(value.ciphertext);
  } catch {
    return false;
  }
}
