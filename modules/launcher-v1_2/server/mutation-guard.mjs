import { createServer } from 'node:http';
import { BLOCK_RESPONSE, isMutationPath } from './guard-contract.mjs';

// Deliberately has no storage import, dependency injection, or enable flag.
// Mount before any body parser or mutation handler. This owns all responses.
export function mutationGuardHandler(request, response) {
  let pathname;
  try {
    pathname = new URL(request.url, 'http://local.invalid').pathname;
  } catch {
    pathname = null;
  }

  const blocked = pathname !== null && isMutationPath(pathname);
  response.writeHead(blocked ? 503 : 404, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
  });
  // Never inspect a ticket, payload, grant, receipt, or alleged capability flag.
  request.resume();
  response.end(JSON.stringify(blocked ? BLOCK_RESPONSE : {
    status: 'NOT_FOUND',
    code: 'NO_ROUTE',
  }));
}

export function createGuardServer() {
  return createServer(mutationGuardHandler);
}
