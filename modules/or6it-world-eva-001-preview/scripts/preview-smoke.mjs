import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { preview } from 'vite';

const configFile = fileURLToPath(new URL('../vite.config.js', import.meta.url));
const server = await preview({
  configFile,
  preview: { host: '127.0.0.1', port: 0, strictPort: false },
});

try {
  const address = server.httpServer.address();
  assert.ok(address && typeof address === 'object', 'Preview must listen on a TCP port.');
  const baseUrl = `http://127.0.0.1:${address.port}`;

  const pageResponse = await fetch(baseUrl);
  assert.equal(pageResponse.status, 200);
  assert.equal(
    pageResponse.headers.get('content-security-policy'),
    "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self'; form-action 'none'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'",
  );
  assert.equal(pageResponse.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(pageResponse.headers.get('x-frame-options'), 'DENY');
  assert.equal(pageResponse.headers.get('referrer-policy'), 'no-referrer');
  assert.equal(
    pageResponse.headers.get('permissions-policy'),
    'camera=(), geolocation=(), microphone=()',
  );

  const html = await pageResponse.text();
  const scriptPath = html.match(/<script[^>]+src="([^"]+)"/)?.[1];
  assert.ok(scriptPath, 'Built page must reference its application bundle.');

  const [scriptResponse, imageResponse] = await Promise.all([
    fetch(new URL(scriptPath, baseUrl)),
    fetch(new URL('/assets/world-eva-001-reference.png', baseUrl)),
  ]);
  assert.equal(scriptResponse.status, 200);
  const script = await scriptResponse.text();
  assert.match(script, /STRUCTURALLY_VALID/);
  assert.match(script, /NOT_AUTHORIZED/);

  assert.equal(imageResponse.status, 200);
  assert.equal(imageResponse.headers.get('content-type'), 'image/png');
  const signature = new Uint8Array(await imageResponse.arrayBuffer()).slice(0, 8);
  assert.deepEqual(signature, new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]));

  console.log('Production preview smoke check passed (headers, app bundle, and EVA image).');
} finally {
  await server.close();
}
