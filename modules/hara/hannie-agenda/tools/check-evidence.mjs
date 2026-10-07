import { readFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const repo = resolve(fileURLToPath(new URL('../', import.meta.url)), '../../..');
const [resultPath, privateSourceDirectory] = process.argv.slice(2);
if (!resultPath) throw new Error('Provide a recorded result.json; optional second argument is the private source snapshot root.');
const r = JSON.parse(readFileSync(resolve(resultPath), 'utf8'));
const sha = b => createHash('sha256').update(b).digest('hex');
const bad = [];
for (const [path, expected] of Object.entries(r.sourceHashes)) {
  if (sha(readFileSync(join(repo, path))) !== expected) bad.push(path);
}
if (sha(JSON.stringify(r.sourceHashes)) !== r.sourceSetSha256) bad.push('source-set-digest');
for (const [path, expected] of Object.entries(r.artifacts)) {
  if (sha(readFileSync(join(resolve(resultPath, '..'), path))) !== expected) bad.push('artifact:' + path);
}
if (privateSourceDirectory) {
  const manifest = JSON.parse(readFileSync(join(repo, 'evidence/hara/d012/source-manifest.json'), 'utf8'));
  for (const [path, expected] of Object.entries(manifest.sources)) {
    if (sha(readFileSync(join(privateSourceDirectory, path))) !== expected) bad.push('private-source:' + path);
  }
  if (sha(JSON.stringify(manifest.sources)) !== manifest.sourceSetSha256) bad.push('private-source-set-digest');
}
console.log(JSON.stringify({ runId: r.runId, hashCheck: bad.length ? 'FAIL' : 'PASS', mismatches: bad,
  privateSourceBytes: privateSourceDirectory ? 'CHECKED' : 'NOT CHECKED', independentReview: 'PENDING',
  boundary: 'Integrity check only; not independent acceptance or official PALACO PROOF.' }));
process.exitCode = bad.length ? 1 : 0;
