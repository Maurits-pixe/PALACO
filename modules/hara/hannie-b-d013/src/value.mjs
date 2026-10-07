import { createHash } from 'node:crypto';
export const sha = text => createHash('sha256').update(text).digest('hex');
export function canonical(v) {
  if (v === null || typeof v === 'string' || typeof v === 'boolean') return JSON.stringify(v);
  if (typeof v === 'number' && Number.isFinite(v)) return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
  if (!v || Object.getPrototypeOf(v) !== Object.prototype) throw Error('INVALID_INPUT');
  for (const d of Object.values(Object.getOwnPropertyDescriptors(v))) if (!('value' in d)) throw Error('INVALID_INPUT');
  return '{' + Object.keys(v).sort().map(k => JSON.stringify(k)+':'+canonical(v[k])).join(',') + '}';
}
export const digest = v => sha(canonical(v));
export function exact(v, keys) {
  canonical(v);
  if (Object.keys(v).sort().join() !== [...keys].sort().join()) throw Error('INVALID_INPUT');
}
export const REQUEST_KEYS = ['operationId','calendarId','eventId','grantId','generation','approvalId','title'];
export const CONTEXT_KEYS = ['owner','tenant','session'];
export function validate(context, request) {
  exact(context, CONTEXT_KEYS); exact(request, REQUEST_KEYS);
  for (const v of [...Object.values(context), ...Object.entries(request).filter(([k]) => k !== 'generation').map(([,v]) => v)]) {
    if (typeof v !== 'string' || !v.length || v.length > 160) throw Error('INVALID_INPUT');
  }
  if (!Number.isSafeInteger(request.generation) || request.generation < 1) throw Error('INVALID_INPUT');
}
