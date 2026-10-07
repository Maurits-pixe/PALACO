import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { createGuardServer } from '../server/mutation-guard.mjs';
import { BLOCK_RESPONSE, MUTATION_PATHS } from '../server/guard-contract.mjs';
import {
  createOperationResult, recordGuardResponse, recordUnknownResult,
} from '../server/client-result.mjs';

async function listen(t, server = createGuardServer()) {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise((resolve, reject) => {
    server.close(error => error ? reject(error) : resolve());
    server.closeAllConnections();
  }));
  return `http://127.0.0.1:${server.address().port}`;
}

function initial() {
  return createOperationResult({
    operationId: 'original-operation',
    bindings: {
      proposalDigest: 'existing-opaque-digest',
      grantId: 'existing-grant',
      idempotencyKey: 'existing-idempotency-key',
      expiry: 'existing-bound-expiry',
      receiptBinding: { reference: 'retained-opaque-reference' },
    },
  });
}

test('all prepare/execute aliases reject before parsing any mutation body', async t => {
  const origin = await listen(t);
  for (const path of MUTATION_PATHS) {
    for (const suffix of ['', '/?enabled=true']) {
      const response = await fetch(origin + path + suffix, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Storage-Deadline-Supported': 'true' },
        body: '{invalid json; capability=true; ticket=consume-me',
      });
      assert.equal(response.status, 503);
      assert.equal(response.headers.get('cache-control'), 'no-store');
      assert.deepEqual(await response.json(), BLOCK_RESPONSE);
    }
  }
});

test('alternate methods and concurrent duplicate requests cannot enable mutations', async t => {
  const origin = await listen(t);
  for (const method of ['GET', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD']) {
    const response = await fetch(origin + '/api/mutations/execute', { method });
    assert.equal(response.status, 503);
    if (method === 'HEAD') assert.equal(await response.text(), '');
    else assert.deepEqual(await response.json(), BLOCK_RESPONSE);
  }
  const results = await Promise.all(Array.from({ length: 6 }, () => fetch(
    origin + '/mutations/execute', {
      method: 'POST',
      body: JSON.stringify({ operationId: 'same-operation', ticketId: 'same-ticket' }),
    },
  )));
  for (const response of results) {
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), BLOCK_RESPONSE);
  }
});

test('unknown paths have no mutation fallback', async t => {
  const origin = await listen(t);
  for (const path of ['/mutations/delete', '/api/mutations/execute-extra', '/']) {
    const response = await fetch(origin + path, { method: 'POST', body: '{}' });
    assert.equal(response.status, 404);
    assert.deepEqual(await response.json(), { status: 'NOT_FOUND', code: 'NO_ROUTE' });
  }
});

test('an exact loopback response blocks only its current request and retains bindings', async t => {
  const origin = await listen(t), expectedUrl = origin + '/mutations/execute';
  const before = initial();
  const after = await recordGuardResponse(before, {
    attemptId: 'first-attempt', expectedUrl,
    response: await fetch(expectedUrl, { method: 'POST', body: '{}' }),
  });
  assert.equal(before.status, 'NOT_ATTEMPTED');
  assert.equal(after.status, 'BLOCKED');
  assert.equal(after.operationId, before.operationId);
  assert.deepEqual(after.bindings, before.bindings);
  assert.equal(after.attempts[0].scope, 'CURRENT_REQUEST_ONLY');
  assert.equal('mustRevert' in after, false);
  assert.equal('receipt' in after, false);
  assert.equal(Object.isFrozen(after.bindings.receiptBinding), true);
});

test('a timeout stays unknown across later repeated blocked attempts', async t => {
  const origin = await listen(t), expectedUrl = origin + '/api/mutations/execute';
  const before = initial();
  let result = recordUnknownResult(before, { attemptId: 'lost-answer', reason: 'TIMEOUT' });
  for (const attemptId of ['later-attempt', 'later-attempt']) {
    result = await recordGuardResponse(result, {
      attemptId, expectedUrl,
      response: await fetch(expectedUrl, { method: 'POST' }),
    });
  }
  assert.equal(result.status, 'RESULT_UNKNOWN');
  assert.equal(result.attempts[0].code, 'TIMEOUT');
  assert.equal(result.attempts[1].status, 'BLOCKED');
  assert.equal(result.attempts[2].status, 'BLOCKED');
  assert.equal(result.operationId, before.operationId);
  assert.deepEqual(result.bindings, before.bindings);
  assert.equal('mustRevert' in result, false);
  assert.equal('receipt' in result, false);
});

test('success, receipt claims, malformed bodies, redirects and wrong origins stay unknown', async t => {
  const server = createServer((request, response) => {
    const mode = new URL(request.url, 'http://local.invalid').searchParams.get('mode');
    if (mode === 'redirect') {
      response.writeHead(302, { Location: '/mutations/execute?mode=valid' });
      response.end();
      return;
    }
    response.writeHead(mode === 'success' ? 200 : 503, {
      'Content-Type': mode === 'html' ? 'text/html' : 'application/json',
    });
    response.end(mode === 'malformed' ? '{' : JSON.stringify(
      mode === 'success' ? { status: 'SUCCEEDED', receipt: { durable: true } }
        : mode === 'receipt' ? { ...BLOCK_RESPONSE, receipt: { durable: true } }
          : BLOCK_RESPONSE,
    ));
  });
  const origin = await listen(t, server);
  for (const mode of ['success', 'receipt', 'malformed', 'redirect', 'html', 'wrong-origin']) {
    const url = origin + '/mutations/execute?mode=' + mode;
    const result = await recordGuardResponse(initial(), {
      attemptId: mode,
      expectedUrl: mode === 'wrong-origin' ? 'http://127.0.0.1:1/mutations/execute' : url,
      response: await fetch(url),
    });
    assert.equal(result.status, 'RESULT_UNKNOWN', mode);
    assert.equal('receipt' in result, false, mode);
    assert.equal('mustRevert' in result, false, mode);
    assert.deepEqual(result.bindings, initial().bindings, mode);
  }
});

test('an actual aborted loopback request is unknown, never a rollback or receipt', async t => {
  const origin = await listen(t, createServer((_request, response) => {
    const timer = setTimeout(() => {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ status: 'SUCCEEDED', receipt: 'unverified' }));
    }, 500);
    response.on('close', () => clearTimeout(timer));
  }));
  let result;
  try {
    await fetch(origin + '/mutations/execute', { method: 'POST', signal: AbortSignal.timeout(25) });
    assert.fail('the request should time out');
  } catch (error) {
    assert.equal(error.name, 'TimeoutError');
    result = recordUnknownResult(initial(), { attemptId: 'timeout', reason: 'TIMEOUT' });
  }
  assert.equal(result.status, 'RESULT_UNKNOWN');
  assert.equal('mustRevert' in result, false);
  assert.equal('receipt' in result, false);
  assert.deepEqual(result.bindings, initial().bindings);
});
