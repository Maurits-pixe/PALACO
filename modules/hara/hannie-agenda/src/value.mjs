import { createHash } from 'node:crypto';

export class CalendarError extends Error {
  constructor(code) { super(code); this.name = 'CalendarError'; this.code = code; }
}
export function deny(code) { throw new CalendarError(code); }
export function plain(value) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype) deny('INVALID_INPUT');
  for (const d of Object.values(Object.getOwnPropertyDescriptors(value))) {
    if (!('value' in d)) deny('INVALID_INPUT');
  }
  return value;
}
export function exact(value, allowed, required = allowed) {
  plain(value);
  if (Object.keys(value).some(k => !allowed.includes(k)) || required.some(k => !Object.hasOwn(value, k))) deny('INVALID_INPUT');
  return value;
}
export function id(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_.:/-]{1,160}$/.test(value)) deny('INVALID_ID');
  return value;
}
export function canonical(value) {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  plain(value);
  return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
}
export function digest(value) { return createHash('sha256').update(canonical(value)).digest('hex'); }
export function freeze(value) {
  if (value && typeof value === 'object') { for (const v of Object.values(value)) freeze(v); Object.freeze(value); }
  return value;
}
export function detached(value) { return freeze(JSON.parse(canonical(value))); }
export const FIELDS = freeze(['title', 'note', 'start', 'end', 'timeZone']);
export const ACTIONS = freeze({ CREATE_OWN_EVENT: [...FIELDS], MOVE_OWN_EVENT: ['start', 'end', 'timeZone'], EDIT_OWN_TEXT: ['title', 'note'] });
export const THRESHOLDS = freeze({ 3: 2, 4: 3, 5: 3, 6: 4, 7: 5 });

function instant(value, zone) {
  if (typeof value !== 'string') deny('INVALID_TIME');
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|[+-]\d{2}:\d{2})$/);
  if (!m) deny('OFFSET_REQUIRED');
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) deny('INVALID_TIME');
  let parts;
  try { parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).formatToParts(ms); }
  catch { deny('INVALID_TIMEZONE'); }
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  if (['year', 'month', 'day', 'hour', 'minute', 'second'].some((k, i) => Number(p[k]) !== Number(m[i + 1]))) deny('DST_OR_OFFSET_MISMATCH');
  return ms;
}
export function normalize(action, changes, before = null) {
  if (!Object.hasOwn(ACTIONS, action)) deny('INVALID_ACTION');
  exact(changes, ACTIONS[action], action === 'CREATE_OWN_EVENT' ? ['title', 'start', 'end', 'timeZone'] : action === 'MOVE_OWN_EVENT' ? ['start', 'end', 'timeZone'] : []);
  if (!Object.keys(changes).length) deny('INVALID_INPUT');
  if ('title' in changes && (typeof changes.title !== 'string' || !changes.title.trim() || changes.title.length > 160)) deny('INVALID_TITLE');
  if ('note' in changes && (typeof changes.note !== 'string' || changes.note.length > 4000)) deny('INVALID_NOTE');
  const after = { ...(before || { note: '' }), ...changes };
  if (action !== 'EDIT_OWN_TEXT') {
    if (typeof after.timeZone !== 'string' || !/^[A-Za-z_]+(?:\/[A-Za-z0-9_+.-]+)*$/.test(after.timeZone)) deny('INVALID_TIMEZONE');
    const start = instant(changes.start, changes.timeZone), end = instant(changes.end, changes.timeZone);
    if (end <= start || end - start > 7 * 86400000) deny('INVALID_DURATION');
    after.start = new Date(start).toISOString(); after.end = new Date(end).toISOString();
  }
  return detached(after);
}
