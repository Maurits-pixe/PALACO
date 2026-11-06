import test from 'node:test';
import assert from 'node:assert/strict';
import { encryptMessage } from '../src/crypto.js';
import { isEncryptedEnvelope } from '../src/envelope.js';
import { createBastionTask } from '../src/bastion.js';
import { createRevisionGuard } from '../src/revision.js';
import { createEncryptedExport, ENCRYPTED_EXPORT_FILENAME } from '../src/export.js';

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

test('malformed envelopes fail closed before any network call', async () => {
  const valid = JSON.parse(await encryptMessage('fixture', 'test passphrase long enough'));
  const variants = [
    { ...valid, version: 2 },
    { ...valid, iterations: 1 },
    { ...valid, iv: 'AA==' },
    { ...valid, salt: 'AA==' },
    { ...valid, ciphertext: 'not-base64!' },
    { ...valid, unexpected: 'field' },
    { ...valid, ciphertext: '' },
  ];
  let networkCalls = 0;
  const options = {
    baseUrl: 'http://localhost:3000/api',
    fetchImpl: async () => { networkCalls += 1; throw new Error('unexpected network call'); },
  };
  for (const variant of variants) {
    const description = JSON.stringify(variant);
    assert.equal(isEncryptedEnvelope(description), false);
    await assert.rejects(createBastionTask(description, options), /versleutelde tekst/);
  }
  assert.equal(isEncryptedEnvelope('x'.repeat(65537)), false);
  assert.equal(networkCalls, 0);
});

test('Bastion confirmation must match submitted ciphertext', async () => {
  const description = await encryptMessage('fixture', 'test passphrase long enough');
  const options = {
    baseUrl: 'http://localhost:3000/api',
    fetchImpl: async () => Response.json({ id: 'task-id', description: 'different ciphertext' }, { status: 201 }),
  };
  await assert.rejects(createBastionTask(description, options), /Geen bevestiging/);
});

test('async encryption results are accepted only for the original input revision', async () => {
  const guard = createRevisionGuard();
  const first = guard.snapshot();
  assert.equal(guard.isCurrent(first), true);
  guard.invalidate(); // user changes the message or passphrase
  assert.equal(guard.isCurrent(first), false);
  const second = guard.snapshot();
  assert.equal(guard.isCurrent(second), true);
  guard.invalidate(); // second edit invalidates even a pending result
  assert.equal(guard.isCurrent(second), false);
  assert.equal(guard.isCurrent(guard.snapshot()), true);
  assert.equal(guard.isCurrent(String(guard.snapshot())), false);
});

test('offline export contains exactly the validated encrypted envelope', async () => {
  const plaintext = 'synthetic offline fixture';
  const passphrase = 'offline test passphrase';
  const envelope = await encryptMessage(plaintext, passphrase);
  const blob = createEncryptedExport(envelope);
  assert.equal(ENCRYPTED_EXPORT_FILENAME, 'aether-envelope-v1.json');
  assert.equal(blob.type, 'application/json');
  assert.equal(await blob.text(), envelope);
  assert.ok(!(await blob.text()).includes(plaintext));
  assert.ok(!(await blob.text()).includes(passphrase));
  assert.throws(() => createEncryptedExport(plaintext), /versleutelde envelop/);
  assert.throws(() => createEncryptedExport('{}'), /versleutelde envelop/);
});

import { readEncryptedImport } from '../src/import.js';

test('offline import accepts only a bounded encrypted v1 envelope', async () => {
  const plaintext = 'synthetic import fixture';
  const passphrase = 'import test passphrase';
  const envelope = await encryptMessage(plaintext, passphrase);
  const fixture = text => ({ size: new TextEncoder().encode(text).byteLength, text: async () => text });
  assert.equal(await readEncryptedImport(fixture(envelope)), envelope);
  assert.ok(!envelope.includes(plaintext));
  assert.ok(!envelope.includes(passphrase));

  for (const invalid of [
    null,
    { size: 65537, text: async () => envelope },
    { size: 0, text: async () => envelope },
    fixture(plaintext),
    fixture('{}'),
    fixture(envelope.replace('AES-GCM', 'not-a-cipher')),
    { size: 10, text: async () => 'x'.repeat(65537) },
    { size: 10, text: async () => { throw new Error('read failure'); } },
  ]) {
    await assert.rejects(readEncryptedImport(invalid));
  }
});

test('offline import has no network side effect and does not grant authority', async () => {
  const encrypted = await encryptMessage('offline only', 'long enough passphrase');
  let networkCalls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { networkCalls += 1; throw new Error('not allowed'); };
  try {
    const imported = await readEncryptedImport({
      size: new TextEncoder().encode(encrypted).byteLength,
      text: async () => encrypted,
    });
    assert.equal(imported, encrypted);
    assert.equal(networkCalls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
