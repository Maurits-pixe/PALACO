import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createDemoServer } from '../server.mjs';
import { encryptMessage } from '../../../modules/aether-preview/src/crypto.js';
import { createBastionTask } from '../../../modules/aether-preview/src/bastion.js';

test('real API persists ciphertext, deduplicates retries, and has no execution routes', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'bastion-test-'));
  const database = join(directory, 'tasks.sqlite');
  let server;
  t.after(async () => {
    if (server?.listening) await new Promise(resolve => server.close(resolve));
    await rm(directory, { recursive: true, force: true });
  });
  const start = async () => {
    server = createDemoServer({ database });
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    return `http://127.0.0.1:${server.address().port}`;
  };
  let base = await start();
  const headers = { Origin: 'http://localhost:5174', 'Content-Type': 'application/json' };
  const description = await encryptMessage('synthetic only', 'a sufficiently long passphrase');
  const task = await createBastionTask(description, {
    baseUrl: `${base}/api`,
    fetchImpl: (url, init) => fetch(url, { ...init, headers: { ...init.headers, Origin: headers.Origin } }),
  });
  const post = (body, extra = {}) => fetch(`${base}/api/tasks`, { method: 'POST', headers, body: JSON.stringify(body), ...extra });
  const retry = await post({ title: 'retry', description });
  assert.equal(retry.status, 200);
  assert.equal((await retry.json()).id, task.id);
  assert.equal((await post({ title: 'empty', description: '' })).status, 400);
  assert.equal((await post({ title: 'plain', description: 'not encrypted' })).status, 400);
  assert.equal((await post(null)).status, 400);
  assert.equal((await post({}, { body: '{' })).status, 400);
  assert.equal((await post({}, { headers: { ...headers, Origin: 'http://localhost.evil.test:5174' } })).status, 403);
  assert.equal((await post({}, { headers: { 'Content-Type': 'application/json' } })).status, 403);
  assert.equal((await post({}, { headers: { ...headers, 'Content-Type': 'text/plain' } })).status, 415);
  assert.equal((await post({}, { body: 'x'.repeat(70001) })).status, 413);
  const preflight = await fetch(`${base}/api/tasks`, { method: 'OPTIONS', headers });
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get('access-control-allow-origin'), headers.Origin);
  for (const method of ['PATCH', 'PUT', 'DELETE']) {
    for (const path of ['/api/tasks', `/api/tasks/${task.id}`, `/api/tasks/${task.id}/complete`]) {
      assert.ok([404, 405].includes((await fetch(base + path, { method })).status));
    }
  }
  assert.equal((await fetch(`${base}/api/execute`, { method: 'POST', headers, body: '{}' })).status, 404);
  await new Promise(resolve => server.close(resolve));
  base = await start();
  const tasks = await (await fetch(`${base}/api/tasks`)).json();
  assert.deepEqual(tasks, [task]);
  assert.deepEqual(await (await fetch(`${base}/health`)).json(), { status: 'local-demo' });
});
