import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import Database from 'better-sqlite3';
import { io } from 'socket.io-client';

const root = new URL('../', import.meta.url);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

test('local backend broadcasts persisted chat, expiration, and blocked mutation audit', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'bastion-preview-'));
  const databasePath = path.join(directory, 'bastion.db');
  const probe = await import('node:net').then(({ createServer }) => new Promise(resolve => {
    const server = createServer();
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  }));
  const child = spawn(process.execPath, ['server.js'], {
    cwd: new URL('.', root),
    env: { ...process.env, BASTION_PORT: String(probe), BASTION_DB_PATH: databasePath },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  const baseUrl = `http://127.0.0.1:${probe}`;
  let client, secondClient;

  t.after(async () => {
    client?.disconnect();
    secondClient?.disconnect();
    child.kill('SIGTERM');
    await Promise.race([once(child, 'exit'), wait(2000)]);
    fs.rmSync(directory, { recursive: true, force: true });
  });

  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/api/messages`);
      if (response.ok) { ready = true; break; }
    } catch {}
    await wait(50);
  }
  assert.equal(ready, true, 'backend should start on its loopback port');

  client = io(baseUrl, { transports: ['websocket'], reconnection: false, autoConnect: false });
  const connected = once(client, 'connect');
  client.connect();
  await connected;
  secondClient = io(baseUrl, { transports: ['websocket'], reconnection: false, autoConnect: false });
  const secondConnected = once(secondClient, 'connect');
  secondClient.connect();
  await secondConnected;
  const initial = await (await fetch(`${baseUrl}/api/messages`)).json();
  assert.deepEqual(initial, []);

  const newMessage = once(client, 'new_message');
  const secondMessage = once(secondClient, 'new_message');
  const acknowledgment = new Promise(resolve => client.emit('send_message', {
    text: 'Realtime preview',
    ttlSeconds: 30
  }, resolve));
  const [[message], [broadcastMessage], ack] = await Promise.all([newMessage, secondMessage, acknowledgment]);
  assert.equal(ack.ok, true);
  assert.equal(message.text, 'Realtime preview');
  assert.equal(broadcastMessage.id, message.id);
  assert.equal(message.expires_at, message.created_at + 30_000);
  assert.deepEqual(await (await fetch(`${baseUrl}/api/messages`)).json(), [message]);

  const destroyEvent = once(secondClient, 'message_destroyed');
  const db = new Database(databasePath);
  db.prepare('UPDATE messages SET expires_at = ? WHERE id = ?').run(Date.now() - 1, message.id);
  const messagesAfterExpiry = await (await fetch(`${baseUrl}/api/messages`)).json();
  assert.deepEqual(messagesAfterExpiry, []);
  assert.deepEqual(await destroyEvent, [{ id: message.id }]);
  db.close();

  const blocked = await fetch(`${baseUrl}/api/mutations/blocked`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'COMPLETE', taskId: 1 })
  });
  assert.equal(blocked.status, 403);
  assert.equal((await blocked.json()).code, 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED');

  const audit = await (await fetch(`${baseUrl}/api/audit`)).json();
  assert.deepEqual(audit.map(entry => entry.action).sort(), [
    'MESSAGE_EXPIRED',
    'MESSAGE_SENT',
    'MUTATION_BLOCKED_NO_D013_BACKEND'
  ]);
});
