import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { webcrypto } from 'node:crypto';
import {
  decryptBytes,
  encryptBytes,
  MAX_PASSPHRASE_LENGTH,
  MIN_PASSPHRASE_LENGTH,
  validateEnvelope
} from '../src/crypto.js';

const root = new URL('../', import.meta.url);
const passphrase = 'correct paard batterij';

test('launcher identity is explicit and preview-only', () => {
  const identity = JSON.parse(fs.readFileSync(new URL('public/.well-known/palaco-app.json', root)));
  assert.deepEqual(identity, {
    appId: 'aether',
    version: '1.0.0-preview.1',
    status: 'preview-blocked',
    description: 'Lokale AES-GCM-bestandskluis — geïsoleerde previewcandidate',
    securityLevel: 'preview-only'
  });
});

test('encrypts and restores arbitrary bytes with an authenticated envelope', async () => {
  const input = new Uint8Array([0, 1, 127, 128, 255]);
  const encrypted = await encryptBytes(input, passphrase, webcrypto);
  const restored = await decryptBytes(encrypted, passphrase, webcrypto);
  assert.deepEqual(restored, input);
  assert.equal(encrypted.cipher, 'AES-GCM-256');
  assert.equal(encrypted.kdf, 'PBKDF2-SHA-256');
  assert.notDeepEqual([...restored], [...new TextEncoder().encode(encrypted.ciphertext)]);
});

test('uses a new salt and nonce for each encryption', async () => {
  const input = new Uint8Array([42]);
  const first = await encryptBytes(input, passphrase, webcrypto);
  const second = await encryptBytes(input, passphrase, webcrypto);
  assert.notEqual(first.salt, second.salt);
  assert.notEqual(first.iv, second.iv);
});

test('rejects incorrect passphrases and modified ciphertext', async () => {
  const encrypted = await encryptBytes(new Uint8Array([1, 2, 3]), passphrase, webcrypto);
  await assert.rejects(decryptBytes(encrypted, 'wrong passphrase', webcrypto));
  const modified = { ...encrypted, ciphertext: encrypted.ciphertext.slice(0, -4) + 'AAAA' };
  await assert.rejects(decryptBytes(modified, passphrase, webcrypto));
});

test('rejects short passphrases and unknown envelope formats', async () => {
  await assert.rejects(
    encryptBytes(new Uint8Array([1]), 'short', webcrypto),
    new RegExp(`minimaal ${MIN_PASSPHRASE_LENGTH}`)
  );
  await assert.rejects(
    decryptBytes({ schema: 'unknown' }, passphrase, webcrypto),
    /Onbekend of ongeldig/
  );
  await assert.rejects(
    encryptBytes(new Uint8Array([1]), 'a'.repeat(MAX_PASSPHRASE_LENGTH + 1), webcrypto),
    new RegExp(`maximaal ${MAX_PASSPHRASE_LENGTH}`)
  );
});

test('supports the full passphrase limit for astral Unicode characters', async () => {
  const unicodePassphrase = '😀'.repeat(MAX_PASSPHRASE_LENGTH);
  const bytes = new Uint8Array([1, 2, 3]);
  const envelope = await encryptBytes(bytes, unicodePassphrase, webcrypto);
  assert.deepEqual(await decryptBytes(envelope, unicodePassphrase, webcrypto), bytes);
  await assert.rejects(
    encryptBytes(bytes, `${unicodePassphrase}😀`, webcrypto),
    new RegExp(`maximaal ${MAX_PASSPHRASE_LENGTH}`)
  );
});

test('validates portable encrypted backup envelopes and rejects malformed data', async () => {
  const envelope = await encryptBytes(new Uint8Array([10, 20, 30]), passphrase, webcrypto);
  assert.equal(validateEnvelope(envelope), envelope);
  assert.throws(() => validateEnvelope({ ...envelope, salt: 'not base64!' }));
  assert.throws(() => validateEnvelope({ ...envelope, iterations: 1 }));
  assert.throws(() => validateEnvelope({ ...envelope, ciphertext: '' }));
});

test('AETHER uses the launcher-configured local origin and no remote font', () => {
  const catalog = fs.readFileSync(new URL('../launcher-v1_2/src/catalog.js', root), 'utf8');
  const stylesheet = fs.readFileSync(new URL('src/style.css', root), 'utf8');
  const viteConfig = fs.readFileSync(new URL('vite.config.js', root), 'utf8');
  const vercel = JSON.parse(fs.readFileSync(new URL('vercel.json', root)));
  assert.match(catalog, /https:\/\/localhost:5174/);
  assert.match(viteConfig, /https:\/\/127\.0\.0\.1:5173/);
  assert.ok(vercel.headers.some(entry =>
    entry.source === '/.well-known/palaco-app.json' &&
    entry.headers.some(header =>
      header.key === 'Access-Control-Allow-Origin' &&
      header.value === 'https://127.0.0.1:5173'
    )
  ));
  assert.doesNotMatch(stylesheet, /https?:\/\//);
});
