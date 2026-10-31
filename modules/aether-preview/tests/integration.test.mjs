import test from 'node:test';
import assert from 'node:assert/strict';
import { encryptMessage } from '../src/crypto.js';
import { isEncryptedEnvelope } from '../src/envelope.js';
import { createBastionTask } from '../src/bastion.js';

test('encryption is randomized, decryptable, and contains no plaintext or passphrase', async () => {
  const text = 'Vertrouwelijk bericht 🔒';
  const passphrase = 'a unique test passphrase';
  const encrypted = await encryptMessage(text, passphrase);
  assert.ok(isEncryptedEnvelope(encrypted));
  assert.notEqual(encrypted, await encryptMessage(text, passphrase));
  assert.ok(!encrypted.includes(text) && !encrypted.includes(passphrase));
  const envelope = JSON.parse(encrypted);
  const material = await crypto.subtle.importKey('raw', new TextEncoder().encode(passphrase), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt: Buffer.from(envelope.salt, 'base64'), iterations: envelope.iterations },
    material, { name: 'AES-GCM', length: 256 }, false, ['decrypt'],
  );
  const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: Buffer.from(envelope.iv, 'base64') }, key, Buffer.from(envelope.ciphertext, 'base64'));
  assert.equal(new TextDecoder().decode(decrypted), text);
  await assert.rejects(encryptMessage(' ', passphrase));
  await assert.rejects(encryptMessage(text, 'short'));
  await assert.rejects(encryptMessage('x'.repeat(16001), passphrase));
});

test('helper sends only ciphertext and checks responses', async () => {
  const description = await encryptMessage('demo', 'another test passphrase');
  const options = { baseUrl: 'http://localhost:3000/api/' };
  const task = await createBastionTask(description, { ...options, fetchImpl: async (url, init) => {
    assert.equal(url, 'http://localhost:3000/api/tasks');
    assert.equal(init.method, 'POST');
    assert.equal(init.credentials, 'omit');
    assert.ok(init.signal instanceof AbortSignal);
    const payload = JSON.parse(init.body);
    assert.equal(payload.description, description);
    assert.deepEqual(Object.keys(payload).sort(), ['description', 'title']);
    return Response.json({ id: 'demo-id', ...payload }, { status: 201 });
  } });
  assert.equal(task.id, 'demo-id');
  for (const fetchImpl of [
    async () => new Response('', { status: 503 }),
    async () => { throw new Error('network'); },
    async () => { throw new DOMException('timeout', 'TimeoutError'); },
    async () => Response.json({}),
    async () => new Response('not json'),
  ]) {
    await assert.rejects(createBastionTask(description, { ...options, fetchImpl }), /Geen bevestiging/);
  }
  for (const baseUrl of ['', 'file:///tmp/api', '******example.org/api', 'https://example.org/api?x=1']) {
    await assert.rejects(createBastionTask(description, { baseUrl }), /API-URL/);
  }
  for (const invalid of ['', ' ', 'plaintext', '{}', 'null', description.replace('AES-GCM', 'unknown')]) {
    assert.equal(isEncryptedEnvelope(invalid), false);
    await assert.rejects(createBastionTask(invalid, options), /versleutelde tekst/);
  }
});
