import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { webcrypto } from 'node:crypto';
import { decryptBytes, encryptBytes, MIN_PASSPHRASE_LENGTH } from '../src/crypto.js';

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
});

test('AETHER uses the launcher-configured local origin and no remote font', () => {
  const catalog = fs.readFileSync(new URL('../../launcher-v1_2/src/catalog.js', root), 'utf8');
  const stylesheet = fs.readFileSync(new URL('src/style.css', root), 'utf8');
  assert.match(catalog, /https:\/\/localhost:5174/);
  assert.doesNotMatch(stylesheet, /https?:\/\//);
});
