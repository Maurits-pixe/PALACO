import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Database from 'better-sqlite3';
import express from 'express';
import { Server } from 'socket.io';

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const host = '127.0.0.1';
const port = Number(process.env.BASTION_PORT ?? 3005);
const databasePath = path.resolve(process.env.BASTION_DB_PATH ?? path.join(moduleDir, '.bastion-preview', 'bastion.db'));
const allowedOrigins = new Set(
  (process.env.BASTION_ALLOWED_ORIGINS ?? 'https://localhost:5175,https://127.0.0.1:5175')
    .split(',')
    .map(origin => origin.trim())
    .filter(Boolean)
);
const isAllowedOrigin = origin => !origin || allowedOrigins.has(origin);

fs.mkdirSync(path.dirname(databasePath), { recursive: true });
const db = new Database(databasePath);
db.pragma('journal_mode = WAL');
db.exec(`
  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER
  );
  CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    user_id TEXT NOT NULL,
    details TEXT NOT NULL,
    timestamp INTEGER NOT NULL
  );
`);

const app = express();
app.use(express.json({ limit: '16kb' }));
app.use('/api', (req, res, next) => {
  if (!isAllowedOrigin(req.get('origin'))) {
    return res.status(403).json({ error: 'ORIGIN_NOT_ALLOWED' });
  }
  return next();
});
const server = http.createServer(app);
const io = new Server(server, {
  allowRequest: (req, callback) => callback(null, isAllowedOrigin(req.headers.origin))
});
const listMessages = db.prepare('SELECT id, sender, text, created_at, expires_at FROM messages WHERE expires_at IS NULL OR expires_at > ? ORDER BY created_at ASC, id ASC');
const listAudit = db.prepare('SELECT id, action, user_id, details, timestamp FROM audit_logs ORDER BY timestamp DESC, id DESC LIMIT 50');
const insertAudit = db.prepare('INSERT INTO audit_logs (action, user_id, details, timestamp) VALUES (?, ?, ?, ?)');

function publishAudit() {
  io.emit('audit_updated', listAudit.all());
}

function removeExpiredMessages() {
  const now = Date.now();
  const expired = db.prepare('SELECT id FROM messages WHERE expires_at IS NOT NULL AND expires_at <= ?').all(now);
  if (!expired.length) return;

  const removeAndAudit = db.transaction(rows => {
    for (const { id } of rows) {
      db.prepare('DELETE FROM messages WHERE id = ?').run(id);
      insertAudit.run('MESSAGE_EXPIRED', 'Preview', `Message ${id} expired`, now);
    }
  });
  removeAndAudit(expired);
  for (const { id } of expired) io.emit('message_destroyed', { id });
  publishAudit();
}

const recordBlockedMutation = db.transaction(({ action, taskId }) => {
  const timestamp = Date.now();
  insertAudit.run(
    'MUTATION_BLOCKED_NO_D013_BACKEND',
    'Preview',
    `${action} blocked for task ${taskId}: no authorized D-013 backend`,
    timestamp
  );
});

const recordInvalidMutation = db.transaction(() => {
  insertAudit.run(
    'MUTATION_BLOCKED_INVALID_REQUEST',
    'Preview',
    'Invalid preview mutation request',
    Date.now()
  );
});

app.get('/api/messages', (_req, res) => {
  removeExpiredMessages();
  res.json(listMessages.all(Date.now()));
});

app.get('/api/audit', (_req, res) => res.json(listAudit.all()));

app.post('/api/mutations/blocked', (req, res) => {
  const { action, taskId } = req.body ?? {};
  if (!['COMPLETE', 'ESCALATE'].includes(action) || !Number.isSafeInteger(taskId) || taskId < 1) {
    recordInvalidMutation();
    publishAudit();
    return res.status(400).json({ error: 'INVALID_PREVIEW_MUTATION' });
  }

  recordBlockedMutation({ action, taskId });
  publishAudit();
  return res.status(403).json({
    code: 'STORAGE_EFFECT_DEADLINE_UNSUPPORTED',
    message: 'Preview mutation denied; no task state was changed.'
  });
});

io.on('connection', socket => {
  removeExpiredMessages();
  socket.emit('init_messages', listMessages.all(Date.now()));
  socket.emit('init_audit', listAudit.all());

  socket.on('send_message', (data, acknowledge) => {
    const text = typeof data?.text === 'string' ? data.text.trim() : '';
    const ttlSeconds = data?.ttlSeconds ?? null;
    if (!text || text.length > 1000 || (ttlSeconds !== null && ttlSeconds !== 30)) {
      if (typeof acknowledge === 'function') acknowledge({ ok: false, error: 'INVALID_MESSAGE' });
      return;
    }

    const createdAt = Date.now();
    const expiresAt = ttlSeconds === null ? null : createdAt + ttlSeconds * 1000;
    const saveMessage = db.transaction(() => {
      const result = db.prepare(
        'INSERT INTO messages (sender, text, created_at, expires_at) VALUES (?, ?, ?, ?)'
      ).run('Preview', text, createdAt, expiresAt);
      insertAudit.run('MESSAGE_SENT', 'Preview', `Message ${result.lastInsertRowid} sent`, createdAt);
      return { id: Number(result.lastInsertRowid), sender: 'Preview', text, created_at: createdAt, expires_at: expiresAt };
    });

    try {
      const message = saveMessage();
      io.emit('new_message', message);
      publishAudit();
      if (typeof acknowledge === 'function') acknowledge({ ok: true, id: message.id });
    } catch {
      if (typeof acknowledge === 'function') acknowledge({ ok: false, error: 'MESSAGE_NOT_SAVED' });
    }
  });
});

removeExpiredMessages();
const expiryTimer = setInterval(removeExpiredMessages, 1000);
expiryTimer.unref();

server.listen(port, host, () => {
  console.log(`Bastion preview backend listening on http://${host}:${port}`);
});

function close() {
  clearInterval(expiryTimer);
  io.close();
  db.close();
}

process.on('SIGINT', close);
process.on('SIGTERM', close);
