import { DatabaseSync } from 'node:sqlite';
import { waitUntil } from './helpers.mjs';
const [path, deadline] = process.argv.slice(2), db = new DatabaseSync(path);
db.exec('BEGIN IMMEDIATE');
process.send({ kind: 'READY' });
function finish(until) {
  waitUntil(until);
  db.exec('COMMIT'); db.close();
  process.send({ kind: 'DONE' }); process.disconnect();
}
if (deadline === 'IPC') process.once('message', msg => finish(msg.holdUntil));
else finish(Number(deadline));
