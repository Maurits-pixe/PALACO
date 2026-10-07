import fs from 'node:fs';
import path from 'node:path';
import https from 'node:https';
import http from 'node:http';
import { spawn, execFileSync } from 'node:child_process';
import { root } from './report.mjs';

export function temporarySubject(prefix) {
  const parent = path.join(root, '.test-tmp');
  fs.mkdirSync(parent, { recursive: true });
  const directory = fs.mkdtempSync(path.join(parent, `${prefix}-`));
  for (const name of ['package.json', 'package-lock.json', 'vite.config.js', 'index.html', 'src', 'scripts', 'dist']) {
    fs.cpSync(path.join(root, name), path.join(directory, name), { recursive: true });
  }
  return directory;
}

export function certificates(directory) {
  const certs = path.join(directory, 'certs');
  fs.mkdirSync(certs, { recursive: true, mode: 0o700 });
  const configPath = path.join(certs, 'openssl.cnf');
  fs.writeFileSync(configPath, '[req]\ndistinguished_name = dn\n[dn]\n');
  const run = args => execFileSync('openssl', args, { cwd: certs, stdio: 'pipe', env: { ...process.env, OPENSSL_CONF: configPath } });
  run(['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'fixture-ca-key.pem', '-out', 'fixture-ca.pem',
    '-days', '1', '-subj', '/CN=PALACO disposable test CA', '-addext', 'basicConstraints=critical,CA:TRUE']);
  run(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'localhost-key.pem', '-out', 'localhost.csr', '-subj', '/CN=localhost']);
  fs.writeFileSync(path.join(certs, 'extensions.cnf'), 'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n');
  run(['x509', '-req', '-in', 'localhost.csr', '-CA', 'fixture-ca.pem', '-CAkey', 'fixture-ca-key.pem', '-CAcreateserial',
    '-out', 'localhost.pem', '-days', '1', '-extfile', 'extensions.cnf']);
  for (const name of ['fixture-ca-key.pem', 'localhost-key.pem']) fs.chmodSync(path.join(certs, name), 0o600);
  return { ca: fs.readFileSync(path.join(certs, 'fixture-ca.pem')),
    key: fs.readFileSync(path.join(certs, 'localhost-key.pem')), cert: fs.readFileSync(path.join(certs, 'localhost.pem')) };
}

export function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https:') ? https : http;
    const req = client.get(url, { ...options, timeout: 2000 }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString('utf8') }));
    });
    req.on('timeout', () => req.destroy(new Error('Fixture request timed out')));
    req.on('error', reject);
  });
}

export function viteProcess(directory, preview = false) {
  const args = [path.join(root, 'node_modules', 'vite', 'bin', 'vite.js')];
  if (preview) args.push('preview');
  args.push('--configLoader', 'native');
  const child = spawn(process.execPath, args, { cwd: directory, stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  child.stdout.on('data', chunk => { log += chunk; });
  child.stderr.on('data', chunk => { log += chunk; });
  const done = new Promise(resolve => child.once('close', (code, signal) => resolve({ code, signal, log })));
  return { child, done, log: () => log,
    async stop() { if (child.exitCode === null) child.kill('SIGTERM'); return done; } };
}

export async function waitForHttps(process, ca) {
  const deadline = performance.now() + 10000;
  while (performance.now() < deadline) {
    if (process.child.exitCode !== null) throw new Error(`Vite exited: ${process.log()}`);
    try { const response = await request('https://127.0.0.1:5173', { ca }); if (response.status === 200) return response; }
    catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Vite did not become ready: ${process.log()}`);
}

export async function expectedExit(process) {
  const timeout = setTimeout(() => process.child.kill('SIGTERM'), 10000);
  const result = await process.done; clearTimeout(timeout);
  return result;
}

export async function metadataFixtures(tls) {
  const config = Object.fromEntries(['aether', 'bastion', '5criptie'].map(id => [id, { mode: 'ok' }]));
  const requests = [];
  const timers = new Set();
  const servers = [];
  for (const [id, port] of [['aether', 5174], ['bastion', 5175], ['5criptie', 5176]]) {
    const server = https.createServer(tls, (req, res) => {
      requests.push({ id, url: req.url, origin: req.headers.origin, time: Date.now() });
      if (req.url !== '/.well-known/palaco-app.json') {
        res.writeHead(200, { 'content-type': 'text/html' }); res.end(`<h1>${id.toUpperCase()} TEST FIXTURE</h1>`); return;
      }
      const mode = config[id].mode;
      const headers = { 'content-type': 'application/json', 'cache-control': 'no-store' };
      if (mode !== 'no-cors') headers['access-control-allow-origin'] = 'https://127.0.0.1:5173';
      if (mode === 'redirect') {
        res.writeHead(302, { ...headers, location: '/redirected' }); res.end(); return;
      }
      res.writeHead(200, headers); res.flushHeaders();
      if (mode === 'no-response') return;
      const data = mode === 'missing-status' ? { appId: id }
        : mode === 'wrong-id' ? { appId: 'wrong', status: 'ready' } : { appId: id, status: 'ready' };
      const body = mode === 'malformed' ? '{invalid' : JSON.stringify(data);
      if (mode === 'slow-body' || mode === 'race') {
        const timer = setTimeout(() => { timers.delete(timer); res.end(body); }, mode === 'slow-body' ? 5200 : 1800);
        timers.add(timer); res.once('close', () => { clearTimeout(timer); timers.delete(timer); });
      } else res.end(body);
    });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
    servers.push(server);
  }
  return { config, requests,
    async close() {
      for (const timer of timers) clearTimeout(timer);
      for (const server of servers) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
    }
  };
}
