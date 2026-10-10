import assert from 'node:assert/strict';
import { createHash, createPrivateKey, createPublicKey, sign, verify } from 'node:crypto';
import { readFile } from 'node:fs/promises';

const vector = JSON.parse(await readFile(new URL('./vectors/6ri9ade-node-reference-v0.1.json', import.meta.url), 'utf8'));
const canonical = value => {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isSafeInteger(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  throw new Error('NON_JSON_REFERENCE');
};
const canonicalBody = canonical(vector.body);
const signingBytes = Buffer.from(vector.domain + canonicalBody, 'utf8');
const envelope = { algorithm: 'Ed25519', body: vector.body, signature: vector.signature };
const envelopeDigest = createHash('sha256').update(canonical(envelope)).digest('hex');
const privateKey = createPrivateKey({
  key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), Buffer.from(vector.seedHex, 'hex')]),
  format: 'der',
  type: 'pkcs8',
});

assert.equal(vector.classification, 'SYNTHETIC_TEST_ONLY');
assert.equal(canonicalBody, vector.canonicalBody);
assert.equal(signingBytes.toString('hex'), vector.signingBytesHex);
assert.equal(envelopeDigest, vector.envelopeDigest);
assert.equal(sign(null, signingBytes, privateKey).toString('base64url'), vector.signature);
assert.equal(
  verify(null, signingBytes, createPublicKey(vector.publicKeyPem), Buffer.from(vector.signature, 'base64url')),
  true,
);
process.stdout.write('6RI9ADE Rust/Node shared primitive vector: PASS (synthetic test key)\n');
