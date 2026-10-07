import { BLOCK_CODE, isMutationPath } from './guard-contract.mjs';

function freezeTree(value, seen = new WeakSet()) {
  if (value && typeof value === 'object' && !seen.has(value)) {
    seen.add(value);
    for (const child of Object.values(value)) freezeTree(child, seen);
    Object.freeze(value);
  }
  return value;
}

function requireId(value, name) {
  if (typeof value !== 'string' || !value.length || value.length > 200) {
    throw new TypeError(`${name} is required`);
  }
}

// bindings are opaque existing operation/proposal identifiers, not authority.
export function createOperationResult({ operationId, bindings }) {
  requireId(operationId, 'operationId');
  if (!bindings || typeof bindings !== 'object' || Array.isArray(bindings)) {
    throw new TypeError('bindings must be an object');
  }
  return freezeTree({
    operationId,
    bindings: structuredClone(bindings),
    status: 'NOT_ATTEMPTED',
    attempts: [],
  });
}

function appendResult(previous, attempt) {
  requireId(attempt.attemptId, 'attemptId');
  const attempts = [...previous.attempts, attempt];
  return freezeTree({
    operationId: previous.operationId,
    bindings: structuredClone(previous.bindings),
    // A later blocked request cannot disprove an earlier uncertain effect.
    status: attempts.some(item => item.status === 'RESULT_UNKNOWN')
      ? 'RESULT_UNKNOWN'
      : 'BLOCKED',
    attempts,
  });
}

export function recordUnknownResult(previous, { attemptId, reason = 'UNTRUSTED_RESPONSE' }) {
  const knownReasons = ['TIMEOUT', 'NETWORK_ERROR', 'UNTRUSTED_RESPONSE'];
  return appendResult(previous, {
    attemptId,
    status: 'RESULT_UNKNOWN',
    code: knownReasons.includes(reason) ? reason : 'UNTRUSTED_RESPONSE',
  });
}

// Call with the fetch Response for this request and its expected guard URL.
// This validates response shape/origin only; it is not a signature or receipt.
// No response can claim SUCCEEDED through this closed demonstration helper.
export async function recordGuardResponse(previous, { attemptId, response, expectedUrl }) {
  try {
    const expected = new URL(expectedUrl);
    const contentType = response?.headers?.get('content-type') ?? '';
    if (!['http:', 'https:'].includes(expected.protocol)
      || expected.username || expected.password || expected.hash
      || !isMutationPath(expected.pathname)
      || !(response instanceof Response)
      || response.redirected || response.url !== expected.href
      || response.status !== 503
      || !/^application\/json(?:\s*;|$)/i.test(contentType)) {
      return recordUnknownResult(previous, { attemptId });
    }
    const body = await response.json();
    if (body === null || typeof body !== 'object' || Array.isArray(body)
      || Object.keys(body).sort().join(',') !== 'code,scope,status'
      || body.status !== 'BLOCKED' || body.code !== BLOCK_CODE
      || body.scope !== 'CURRENT_REQUEST_ONLY') {
      return recordUnknownResult(previous, { attemptId });
    }
    return appendResult(previous, {
      attemptId,
      status: 'BLOCKED',
      code: BLOCK_CODE,
      scope: 'CURRENT_REQUEST_ONLY',
    });
  } catch {
    return recordUnknownResult(previous, { attemptId });
  }
}
