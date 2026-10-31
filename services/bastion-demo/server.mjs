import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { pathToFileURL } from 'node:url';
import { isEncryptedEnvelope } from '../../modules/aether-preview/src/envelope.js';

export function createDemoServer({
  database = ':memory:',
  origins = ['http://localhost:5174', 'http://localhost:5175'],
} = {}) {
  const db = new DatabaseSync(database);
  db.exec('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL UNIQUE)');
  const server = http.createServer(async (req, res) => {
    const origin = req.headers.origin;
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    const reply = (status, data) => { res.writeHead(status); res.end(JSON.stringify(data)); };
    if (origin && !origins.includes(origin)) return reply(403, { error: 'ORIGIN_DENIED' });
    if (origin) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Vary', 'Origin');
    }
    if (req.method === 'GET' && req.url === '/health') return reply(200, { status: 'local-demo' });
    if (req.url !== '/api/tasks') return reply(404, { error: 'NOT_FOUND' });
    if (req.method === 'OPTIONS') {
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
      return reply(204);
    }
    if (!['GET', 'POST'].includes(req.method)) return reply(405, { error: 'METHOD_NOT_ALLOWED' });
    try {
      if (req.method === 'GET') return reply(200, db.prepare('SELECT * FROM tasks ORDER BY rowid DESC').all());
      if (!origin || !origins.includes(origin)) return reply(403, { error: 'ORIGIN_REQUIRED' });
      if (req.headers['content-type']?.split(';')[0].trim() !== 'application/json') {
        return reply(415, { error: 'JSON_REQUIRED' });
      }
      const chunks = [];
      let bytes = 0;
      for await (const chunk of req) {
        bytes += chunk.length;
        if (bytes > 70000) {
          reply(413, { error: 'PAYLOAD_TOO_LARGE' });
          return;
        }
        chunks.push(chunk);
      }
      let payload;
      try { payload = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { return reply(400, { error: 'INVALID_JSON' }); }
      if (!payload || !isEncryptedEnvelope(payload.description)
        || typeof payload.title !== 'string' || !payload.title.trim() || payload.title.length > 120) {
        return reply(400, { error: 'INVALID_TASK' });
      }
      const existing = db.prepare('SELECT * FROM tasks WHERE description = ?').get(payload.description);
      if (existing) return reply(200, existing);
      if (db.prepare('SELECT count(*) AS total FROM tasks').get().total >= 1000) {
        return reply(409, { error: 'DEMO_CAPACITY_REACHED' });
      }
      const task = { id: randomUUID(), title: payload.title.trim(), description: payload.description };
      db.prepare('INSERT INTO tasks (id, title, description) VALUES (?, ?, ?)').run(task.id, task.title, task.description);
      return reply(201, task);
    } catch {
      if (!res.headersSent) reply(503, { error: 'STORAGE_UNAVAILABLE' });
    }
  });
  server.requestTimeout = 15000;
  server.headersTimeout = 10000;
  server.on('close', () => db.close());
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.env.BASTION_DEMO_MODE !== 'local-only') throw new Error('Explicit local-only demo mode required');
  const server = createDemoServer({
    database: process.env.BASTION_DATABASE || ':memory:',
    origins: (process.env.BASTION_ALLOWED_ORIGINS || 'http://localhost:5174,http://localhost:5175').split(','),
  });
  server.listen(3000, process.env.BASTION_HOST || '127.0.0.1', () => console.log('Bastion local demo listening on port 3000'));
}
