import { DatabaseSync } from 'node:sqlite';
import { join } from 'node:path';
import { waitUntil } from './helpers.mjs';
const [dir, time, route] = process.argv.slice(2), deadline = Number(time);
const db = new DatabaseSync(join(dir, 'calendar.sqlite'), { readOnly: true, timeout: 5000 });
process.send({ kind: 'READY' });
process.once('message', () => {
  let zeroAfterExpiry = false, firstEffectAt = null, effects = 0, polls = 0;
  const stopAt = deadline + (route === 'primitive-calibration' ? 5000 : 150);
  do {
    effects = db.prepare('SELECT COUNT(*) n FROM events').get().n; polls++;
    const now = Date.now();
    if (!effects && now >= deadline) zeroAfterExpiry = true;
    if (effects) { firstEffectAt = now; break; }
    waitUntil(now + 5);
  } while (Date.now() <= stopAt);
  db.close();
  process.send({ kind: 'DONE', zeroAfterExpiry, firstEffectAt, effects, polls });
  process.disconnect();
});
