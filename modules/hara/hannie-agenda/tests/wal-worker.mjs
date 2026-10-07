import { writeFileSync, existsSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { fixture, prepared, seedCommitted, databaseState, waitUntil } from './helpers.mjs';
import { canonical } from '../src/value.mjs';
const [dir, route, deadlineKind] = process.argv.slice(2);
const f = fixture({ dir, realClock: true, expiresMs: deadlineKind === 'approval-only' ? 60000 : 1200 });
const p = prepared(f);
let deadline = p.approval.expiresAt;
if (deadlineKind === 'approval-only') {
  deadline = Date.now() + 1200;
  const a = f.db.prepare('SELECT * FROM approvals WHERE id=?').get(p.approval.approvalId), body = JSON.parse(a.body);
  body.expiresAt = deadline;
  f.db.prepare('UPDATE approvals SET body=? WHERE id=?').run(canonical(body), a.id);
}
process.send({ kind: 'READY', deadline });
process.once('message', () => {
  const before = databaseState(f.db), counts = { ...f.state.counts }, startMs = Date.now();
  writeFileSync(join(dir, 'arm'), 'one exact WAL write');
  let code = null;
  if (route === 'primitive-calibration') {
    seedCommitted(f, p); // Privileged history fixture, not the candidate mutation API.
  } else {
    try { f.adapter.execute('HANNIE', p); } catch (e) { code = e.code; }
    waitUntil(deadline + 150);
    try { f.adapter.execute('HANNIE', p); } catch (e) { if (code !== e.code) throw e; }
  }
  const endMs = Date.now(), unchanged = databaseState(f.db) === before, noAuthorityCalls = canonical(f.state.counts) === canonical(counts);
  const eventCount = f.db.prepare('SELECT COUNT(*) n FROM events').get().n;
  const injectorReached = existsSync(join(dir, 'native.jsonl'));
  if (existsSync(join(dir, 'arm'))) unlinkSync(join(dir, 'arm'));
  f.close();
  process.send({ kind: 'DONE', route, deadlineKind, code, deadline, startMs, endMs, unchanged, noAuthorityCalls, eventCount, injectorReached });
  process.disconnect();
});
