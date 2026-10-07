import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

export const root = fileURLToPath(new URL('../', import.meta.url));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
export function sourceBinding() {
  const files = ['index.html', 'package.json', 'package-lock.json', 'vite.config.js', 'ACCEPTANCE.md'];
  function walk(dir) {
    for (const entry of fs.readdirSync(path.join(root, dir), { withFileTypes: true })) {
      const relative = path.posix.join(dir, entry.name);
      entry.isDirectory() ? walk(relative) : files.push(relative);
    }
  }
  walk('src');
  walk('scripts');
  walk('server');
  return Object.fromEntries(files.sort().map(file => [file, sha(fs.readFileSync(path.join(root, file)))]));
}
export function createReport(suite, harnessUrl, limits = []) {
  const rows = [];
  const runId = crypto.randomUUID();
  const started = new Date().toISOString();
  const binding = sourceBinding();
  const harnessHash = sha(fs.readFileSync(fileURLToPath(harnessUrl)));
  async function check(id, fn, method = 'deterministic controller harness') {
    try {
      const observed = await fn();
      rows.push({ id, outcome: 'PASS', method, observed: observed ?? null });
    } catch (error) {
      rows.push({ id, outcome: 'FAIL', method, error: error.stack });
    }
    console.log(JSON.stringify(rows.at(-1)));
  }
  function finish(extra = {}) {
    const unchanged = JSON.stringify(binding) === JSON.stringify(sourceBinding());
    if (!unchanged) rows.push({ id: 'SOURCE-UNCHANGED-DURING-RUN', outcome: 'FAIL' });
    const counts = { pass: rows.filter(row => row.outcome === 'PASS').length, fail: rows.filter(row => row.outcome === 'FAIL').length, total: rows.length };
    const report = { suite, runId, started, finished: new Date().toISOString(),
      runtime: { node: process.version, v8: process.versions.v8, platform: process.platform },
      productionSourceHashes: binding, harnessSha256: harnessHash, unchangedDuringRun: unchanged,
      counts, limits, ...extra, tests: rows };
    fs.mkdirSync(path.join(root, 'evidence'), { recursive: true });
    const destination = path.join(root, 'evidence', `${suite}-${runId}.json`);
    fs.writeFileSync(destination, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ suite, runId, counts, evidence: destination }));
    process.exitCode = counts.fail ? 1 : 0;
    return report;
  }
  return { check, finish };
}
