import test from 'node:test';
import assert from 'node:assert/strict';
import { me, BFF } from './mobile/helpers.mjs';

function fixture({ status = 200, type = 'application/json; charset=utf-8', body = '{"accountId":"TST-alpha"}' } = {}) {
  let disposed = false;
  const response = {
    status: () => status,
    ok: () => status >= 200 && status < 300,
    headers: () => ({ 'content-type': type }),
    body: async () => Buffer.from(body),
    dispose: async () => { disposed = true; },
  };
  const page = {
    evaluate: () => { throw new Error('Page execution context is navigating'); },
    context: () => ({ request: { get: async (url, options) => {
      assert.equal(url, BFF + '/api/me');
      assert.equal(options.maxRedirects, 0);
      assert.equal(options.failOnStatusCode, false);
      assert.equal(options.timeout, 8000);
      assert.equal(options.headers['Cache-Control'], 'no-store');
      return response;
    } } }),
  };
  return { page, disposed: () => disposed };
}

test('account readback uses the existing context despite page navigation', async () => {
  const f = fixture();
  assert.deepEqual(await me(f.page), { status: 200, data: { accountId: 'TST-alpha' } });
  assert.equal(f.disposed(), true);
});

test('denied, redirect and unavailable responses never yield account data', async () => {
  for (const status of [302, 401, 403, 503]) {
    const f = fixture({ status });
    assert.deepEqual(await me(f.page), { status, data: null });
    assert.equal(f.disposed(), true);
  }
});

test('malformed, non-JSON and oversized responses fail and are disposed', async () => {
  for (const options of [{ body: '{' }, { type: 'text/html' }, { body: 'x'.repeat(16385) }]) {
    const f = fixture(options);
    await assert.rejects(me(f.page));
    assert.equal(f.disposed(), true);
  }
});

test('transport errors remain failures without a retry or session replacement', async () => {
  let calls = 0;
  const page = { context: () => ({ request: { get: async () => {
    calls++;
    throw new Error('transport unavailable');
  } } }) };
  await assert.rejects(me(page), /transport unavailable/);
  assert.equal(calls, 1);
});
